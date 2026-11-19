import json

import pytest

from chrome_devtools import PAGE_TEXT_SCRIPT, CdpError, CdpSession, Page, PageTarget

TARGET = PageTarget(
    id="B2",
    title="Settings",
    url="chrome://settings/",
    websocket_url="ws://127.0.0.1/devtools/page/B2",
)


class FakeSocket:
    """A socket that answers Runtime.evaluate from a table of expressions."""

    def __init__(self, values=None, events=0):
        self.values = values or {}
        self.events = events
        self.sent = []
        self.closed = False
        self._replies = []

    def send(self, payload):
        message = json.loads(payload)
        self.sent.append(message)

        for _ in range(self.events):
            self._replies.append({"method": "Page.loadEventFired", "params": {}})
        self.events = 0

        expression = message["params"].get("expression")
        value = self.values.get(expression)
        if isinstance(value, list):
            value = value.pop(0) if len(value) > 1 else value[0]
        self._replies.append({"id": message["id"], "result": {"result": {"value": value}}})

    def recv(self):
        return json.dumps(self._replies.pop(0))

    def close(self):
        self.closed = True


class FailingSocket(FakeSocket):
    def send(self, payload):
        message = json.loads(payload)
        self.sent.append(message)
        self._replies.append(
            {"id": message["id"], "error": {"code": -32000, "message": "Cannot evaluate"}}
        )


def page_with(values, events=0):
    socket = FakeSocket(values, events=events)
    return Page(TARGET, CdpSession(socket, timeout=1.0), timeout=1.0), socket


def test_a_command_carries_an_id_and_its_parameters():
    """Replies arrive out of order, so the id is the only way to pair them."""
    socket = FakeSocket({"1 + 1": 2})
    session = CdpSession(socket, timeout=1.0)

    session.call("Runtime.evaluate", expression="1 + 1", returnByValue=True)

    assert socket.sent[0]["method"] == "Runtime.evaluate"
    assert socket.sent[0]["id"] == 1
    assert socket.sent[0]["params"]["expression"] == "1 + 1"


def test_each_command_gets_a_new_id():
    socket = FakeSocket({"1": 1})
    session = CdpSession(socket, timeout=1.0)

    session.call("Runtime.evaluate", expression="1")
    session.call("Runtime.evaluate", expression="1")

    assert [message["id"] for message in socket.sent] == [1, 2]


def test_events_arriving_before_the_reply_are_skipped():
    """A page emits events unasked; they must not be taken for an answer."""
    socket = FakeSocket({"document.title": "Settings"}, events=3)
    session = CdpSession(socket, timeout=1.0)

    result = session.call("Runtime.evaluate", expression="document.title")

    assert result["result"]["value"] == "Settings"


def test_a_protocol_error_is_raised_not_returned():
    session = CdpSession(FailingSocket(), timeout=1.0)

    with pytest.raises(CdpError, match="Cannot evaluate"):
        session.call("Runtime.evaluate", expression="boom")


def test_the_page_title_comes_from_the_document():
    """The window title carries ' - Google Chrome'; the document does not."""
    page, _ = page_with({"document.title": "Settings"})

    assert page.title == "Settings"


def test_the_page_address_is_read_live():
    """Discovery data goes stale the moment the page navigates."""
    page, _ = page_with({"location.href": "chrome://settings/"})

    assert page.url == "chrome://settings/"


def test_page_text_is_collected_through_shadow_roots():
    """innerText returns nothing on chrome:// pages, as measured."""
    page, socket = page_with({PAGE_TEXT_SCRIPT: "Appearance\nPrivacy and security"})

    assert "Privacy and security" in page.text()
    assert "shadowRoot" in socket.sent[0]["params"]["expression"]


def test_waiting_for_text_that_renders_late():
    """Settings paints its sections after the target already exists."""
    page, _ = page_with({PAGE_TEXT_SCRIPT: ["", "", "Appearance"]})

    assert page.contains("Appearance", timeout=5)


def test_text_that_never_appears_is_a_false_not_a_timeout():
    """The check wants to attach the page text before it fails."""
    page, _ = page_with({PAGE_TEXT_SCRIPT: "Appearance"})

    assert not page.contains("Downloads", timeout=0.5)


def test_closing_the_page_closes_the_socket():
    page, socket = page_with({})

    page.close()

    assert socket.closed
