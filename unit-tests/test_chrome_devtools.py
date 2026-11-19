import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from chrome_devtools import PORT_FILE_NAME, DevTools, read_port
from waiting import WaitTimeout

NEW_TAB = {
    "id": "A1",
    "type": "page",
    "title": "New Tab",
    "url": "chrome://newtab/",
    "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/A1",
}

SETTINGS = {
    "id": "B2",
    "type": "page",
    "title": "Settings",
    "url": "chrome://settings/",
    "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/B2",
}

SERVICE_WORKER = {
    "id": "C3",
    "type": "service_worker",
    "title": "Service Worker",
    "url": "chrome-extension://abc/worker.js",
    "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/C3",
}


@pytest.fixture
def endpoint():
    """A stand-in for the browser's HTTP endpoint, serving what a test sets."""
    state = SimpleNamespace(
        targets=[],
        version={"Browser": "Chrome/157.0.0.0", "Protocol-Version": "1.3"},
        devtools=None,
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = state.version if self.path == "/json/version" else state.targets
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state.devtools = DevTools(server.server_address[1], timeout=2.0)
    yield state
    server.shutdown()
    server.server_close()


def test_the_port_is_read_from_the_file_chrome_writes(tmp_path):
    """Launching with port 0 is the only way to avoid collisions."""
    (tmp_path / PORT_FILE_NAME).write_text("8978\n/devtools/browser/f214\n", encoding="utf-8")

    assert read_port(tmp_path, timeout=1) == 8978


def test_waiting_for_the_port_file_to_appear(tmp_path):
    """The file is written when the socket binds, not when Chrome starts."""
    port_file = tmp_path / PORT_FILE_NAME
    timer = threading.Timer(0.3, lambda: port_file.write_text("1234\n", encoding="utf-8"))
    timer.start()
    try:
        assert read_port(tmp_path, timeout=5) == 1234
    finally:
        timer.cancel()


def test_a_half_written_port_file_is_not_an_error(tmp_path):
    """The file is read while Chrome is writing it, so garbage is expected."""
    port_file = tmp_path / PORT_FILE_NAME
    port_file.write_text("", encoding="utf-8")
    timer = threading.Timer(0.3, lambda: port_file.write_text("4321\n", encoding="utf-8"))
    timer.start()
    try:
        assert read_port(tmp_path, timeout=5) == 4321
    finally:
        timer.cancel()


def test_a_browser_that_never_publishes_a_port_times_out(tmp_path):
    """Better a named timeout than a connection refused ten layers down."""
    with pytest.raises(WaitTimeout, match=PORT_FILE_NAME):
        read_port(tmp_path, timeout=0.5)


def test_only_page_targets_are_reported(endpoint):
    """Extensions ship service workers; a fresh profile already has four."""
    endpoint.targets = [NEW_TAB, SERVICE_WORKER, SETTINGS]

    assert [page.url for page in endpoint.devtools.pages()] == [NEW_TAB["url"], SETTINGS["url"]]


def test_a_page_is_found_by_the_start_of_its_address(endpoint):
    """Chrome appends a trailing slash, so equality would be wrong."""
    endpoint.targets = [NEW_TAB, SETTINGS]

    found = endpoint.devtools.page("chrome://settings")

    assert found.title == "Settings"
    assert found.websocket_url.endswith("/B2")


def test_waiting_for_a_page_that_opens_later(endpoint):
    """Settings appeared 0.77s after the menu click when measured."""
    endpoint.targets = [NEW_TAB]
    timer = threading.Timer(0.3, lambda: endpoint.targets.append(SETTINGS))
    timer.start()
    try:
        assert endpoint.devtools.page("chrome://settings", timeout=5).id == "B2"
    finally:
        timer.cancel()


def test_a_page_that_never_appears_raises(endpoint):
    endpoint.targets = [NEW_TAB]

    with pytest.raises(WaitTimeout, match="chrome://settings"):
        endpoint.devtools.page("chrome://settings", timeout=0.5)


def test_find_page_answers_none_instead_of_raising(endpoint):
    """Checks need the list of open pages for the report, not a traceback."""
    endpoint.targets = [NEW_TAB]

    assert endpoint.devtools.find_page("chrome://settings", timeout=0.5) is None


def test_the_browser_reports_its_version(endpoint):
    assert endpoint.devtools.version()["Protocol-Version"] == "1.3"
