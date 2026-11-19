from __future__ import annotations

import contextlib
import json
import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reporting import step
from waiting import WaitTimeout, wait_until

logger = logging.getLogger(__name__)

PORT_FILE_NAME = "DevToolsActivePort"
PAGE_TARGET_TYPE = "page"


class DevToolsUnavailable(RuntimeError):
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
