from __future__ import annotations

import contextlib
import json
import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import websocket

from reporting import step
from waiting import WaitTimeout, wait_until

logger = logging.getLogger(__name__)

PORT_FILE_NAME = "DevToolsActivePort"
PAGE_TARGET_TYPE = "page"

PAGE_TEXT_SCRIPT = """
(() => {
  const parts = [];
  const walk = (node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent.trim();
      if (text) parts.push(text);
      return;
    }
    if (node.shadowRoot) walk(node.shadowRoot);
    for (const child of node.childNodes) walk(child);
  };
  walk(document.body);
  return parts.join("\\n");
})()
"""


class DevToolsUnavailable(RuntimeError):
    pass


class CdpError(RuntimeError):
    pass


@dataclass(frozen=True)
class PageTarget:
    """One inspectable page, as the browser describes it."""

    id: str
    title: str
    url: str
    websocket_url: str


def _page_target(entry: dict[str, Any]) -> PageTarget:
    """Build a target out of one /json/list entry."""
    return PageTarget(
        id=str(entry.get("id", "")),
        title=str(entry.get("title", "")),
        url=str(entry.get("url", "")),
        websocket_url=str(entry.get("webSocketDebuggerUrl", "")),
    )


def read_port(profile_directory: str | Path, *, timeout: float = 30.0) -> int:
    """Wait for the port Chrome publishes inside its profile directory."""
    port_file = Path(profile_directory) / PORT_FILE_NAME

    def published() -> int | None:
        lines = port_file.read_text(encoding="utf-8").splitlines()
        return int(lines[0]) if lines else None

    return wait_until(
        published,
        timeout=timeout,
        description=f"Chrome to publish its DevTools port in {PORT_FILE_NAME}",
        ignore=(OSError, ValueError),
    )


class DevTools:
    """The browser's DevTools endpoint, which knows what pages are open."""

    def __init__(self, port: int, timeout: float = 10.0) -> None:
        self._port = port
        self._timeout = timeout

    @classmethod
    def attach(cls, profile_directory: str | Path, *, timeout: float = 30.0) -> DevTools:
        """Read the port Chrome published and talk to that endpoint."""
        port = read_port(profile_directory, timeout=timeout)
        logger.info("devtools endpoint listening on port %s", port)
        return cls(port, timeout=timeout)

    @property
    def port(self) -> int:
        """The loopback port the browser is listening on."""
        return self._port

    def _get(self, path: str) -> Any:
        url = f"http://127.0.0.1:{self._port}{path}"
        with urllib.request.urlopen(url, timeout=self._timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def version(self) -> dict[str, str]:
        """What the browser reports about itself and the protocol."""
        return self._get("/json/version")

    def pages(self) -> list[PageTarget]:
        """Every inspectable page the browser has open right now."""
        return [
            _page_target(entry)
            for entry in self._get("/json/list")
            if entry.get("type") == PAGE_TARGET_TYPE
        ]

    def page(self, url_prefix: str = "", *, timeout: float | None = None) -> PageTarget:
        """Wait for a page whose address starts with ``url_prefix``."""
        description = f"a page whose address starts with {url_prefix!r}"
        with step(f"wait for {description}"):
            return wait_until(
                lambda: self._first_page(url_prefix),
                timeout=self._timeout if timeout is None else timeout,
                description=description,
                ignore=(OSError, ValueError),
            )

    def find_page(self, url_prefix: str = "", *, timeout: float | None = None) -> PageTarget | None:
        """Wait for a matching page, answering None instead of raising."""
        with contextlib.suppress(WaitTimeout):
            return self.page(url_prefix, timeout=timeout)
        return None

    def _first_page(self, url_prefix: str) -> PageTarget | None:
        for target in self.pages():
            if target.url.startswith(url_prefix):
                return target
        return None


class CdpSession:
    """One WebSocket conversation with a page, where commands carry an id."""

    def __init__(self, socket: Any, timeout: float = 10.0) -> None:
        self._socket = socket
        self._timeout = timeout
        self._last_id = 0

    @classmethod
    def connect(cls, websocket_url: str, *, timeout: float = 10.0) -> CdpSession:
        """Open the socket a page target advertises."""
        logger.debug("opening a devtools session on %s", websocket_url)
        return cls(websocket.create_connection(websocket_url, timeout=timeout), timeout)

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        """Send one command and wait for the reply carrying the same id."""
        self._last_id += 1
        message_id = self._last_id
        self._socket.send(json.dumps({"id": message_id, "method": method, "params": params}))

        while True:
            message = json.loads(self._socket.recv())
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise CdpError(f"{method} failed: {message['error']}")
            return message.get("result", {})

    def close(self) -> None:
        """Hang up. Safe when the browser has already gone away."""
        with contextlib.suppress(OSError, websocket.WebSocketException):
            self._socket.close()


class Page:
    """A live page. UIA sees one opaque node here; this sees the content."""

    def __init__(self, target: PageTarget, session: CdpSession, timeout: float = 10.0) -> None:
        self._target = target
        self._session = session
        self._timeout = timeout

    @classmethod
    def attach(cls, target: PageTarget, *, timeout: float = 10.0) -> Page:
        """Open a session with ``target`` and speak to it."""
        return cls(target, CdpSession.connect(target.websocket_url, timeout=timeout), timeout)

    @property
    def url(self) -> str:
        """Where the page is now, which the discovery listing may predate."""
        return str(self._evaluate("location.href") or "")

    @property
    def title(self) -> str:
        """The page title, read from the document rather than the window."""
        return str(self._evaluate("document.title") or "")

    def text(self) -> str:
        """All text, including what Chrome's own pages hide in shadow roots."""
        return str(self._evaluate(PAGE_TEXT_SCRIPT) or "")

    def contains(self, fragment: str, *, timeout: float | None = None) -> bool:
        """Wait for ``fragment`` to show up in the page text."""
        with contextlib.suppress(WaitTimeout):
            wait_until(
                lambda: fragment in self.text() or None,
                timeout=self._timeout if timeout is None else timeout,
                description=f"the page to show {fragment!r}",
            )
            return True
        return False

    def close(self) -> None:
        """Close the session, not the tab."""
        self._session.close()

    def _evaluate(self, expression: str) -> Any:
        result = self._session.call("Runtime.evaluate", expression=expression, returnByValue=True)
        return result.get("result", {}).get("value")
