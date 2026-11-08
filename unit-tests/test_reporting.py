import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

import reporting
from chrome_checks import check_menu_has_items, check_window_title_contains
from reporting import AllureBackend, NullBackend, attach_file, attach_text, step, use_backend


class RecordingBackend:
    def __init__(self):
        self.steps = []
        self.depths = []
        self.attachments = []
        self._open = []

    @contextmanager
    def step(self, name):
        self.steps.append(name)
        self.depths.append(len(self._open))
        self._open.append(name)
        try:
            yield
        finally:
            self._open.pop()

    def attach_text(self, name, text):
        self.attachments.append((name, text))

    def attach_file(self, name, path):
        self.attachments.append((name, str(path)))

    @property
    def unclosed(self):
        return list(self._open)


class FakeChrome:
    def __init__(self, title="about:blank - Google Chrome"):
        self.title = title
        self.is_running = True
        self.profile_directory = Path("/tmp/test-conductor-chrome-abc")


class FakeMenu:
    def __init__(self, names=()):
        self._names = list(names)

    def item_names(self):
        return list(self._names)

    @property
    def is_open(self):
        return bool(self._names)

    def has_item(self, label):
        return str(label) in self._names


class FakeAttach:
    def __init__(self):
        self.bodies = []
        self.files = []

    def __call__(self, body, name=None, attachment_type=None):
        self.bodies.append((body, name, attachment_type))

    def file(self, source, name=None, attachment_type=None):
        self.files.append((source, name, attachment_type))


class FakeAllure:
    def __init__(self):
        self.attach = FakeAttach()
        self.attachment_type = SimpleNamespace(TEXT="TEXT", PNG="PNG", JSON="JSON")
        self.steps = []

    def step(self, name):
        self.steps.append(name)
        return nullcontext()


@pytest.fixture
def recorder():
    """Install a recording backend for one test, then restore detection."""
    backend = RecordingBackend()
    use_backend(backend)
    yield backend
    use_backend(None)


def test_a_step_does_not_change_what_its_body_does():
    """Reporting is an observer: a step must not alter what it wraps."""
    use_backend(None)
    results = []

    with step("do the thing"):
        results.append("done")

    assert results == ["done"]


def test_a_failure_inside_a_step_propagates(recorder):
    """Swallowing the exception would turn a failing test green."""
    with pytest.raises(AssertionError, match="deliberate"), step("do the thing"):
        raise AssertionError("deliberate")

    assert recorder.steps == ["do the thing"]


def test_a_step_is_closed_even_when_the_body_raises(recorder):
    """Otherwise later steps become children of the failed one."""
    with pytest.raises(RuntimeError), step("outer"):
        raise RuntimeError("boom")

    assert recorder.unclosed == []


def test_steps_are_recorded_in_the_order_they_happen(recorder):
    with step("first"):
        pass
    with step("second"):
        pass

    assert recorder.steps == ["first", "second"]


def test_nested_steps_are_nested(recorder):
    """Nesting is what makes a failure locatable in the report."""
    with step("open the application menu"):
        with step("click the menu button"):
            pass
        with step("wait for the items"):
            pass

    assert recorder.steps == [
        "open the application menu",
        "click the menu button",
        "wait for the items",
    ]
    assert recorder.depths == [0, 1, 1]


def test_attachments_reach_the_backend(recorder, tmp_path):
    screenshot = tmp_path / "window.png"
    screenshot.write_bytes(b"not really a png")

    attach_text("notes", "some text")
    attach_file("window", screenshot)

    assert recorder.attachments == [("notes", "some text"), ("window", str(screenshot))]


def test_a_check_reports_itself_as_a_step(recorder):
    """One check call, one report step, no reporting code in the test."""
    check_window_title_contains(FakeChrome(title="Google Chrome"), "Chrome")

    assert recorder.steps == ["check the window title contains 'Chrome'"]


def test_a_failing_check_still_records_its_step(recorder):
    """Recorded before the assertion runs, or failures never appear."""
    with pytest.raises(AssertionError):
        check_window_title_contains(FakeChrome(title="New Tab"), "Google Chrome")

    assert recorder.steps == ["check the window title contains 'Google Chrome'"]


def test_a_check_attaches_what_it_actually_saw(recorder):
    """The items actually present belong in the report, pass or fail."""
    check_menu_has_items(FakeMenu(["Settings", "History"]), ["Settings"])

    names = [name for name, _ in recorder.attachments]
    assert "menu items present" in names
    body = dict(recorder.attachments)["menu items present"]
    assert "History" in body


def test_the_null_backend_is_used_when_allure_is_absent(monkeypatch):
    """None in sys.modules makes `import allure` fail, as a bare suite would."""
    monkeypatch.setitem(sys.modules, "allure", None)

    assert isinstance(reporting._detect_backend(), NullBackend)


def test_allure_is_used_when_it_is_installed():
    """Installation is the switch; declaring the dependency is enough."""
    assert isinstance(reporting._detect_backend(), AllureBackend)


def test_the_backend_is_detected_once_and_remembered():
    use_backend(None)
    first = reporting.backend()

    assert reporting.backend() is first


def test_the_allure_backend_delegates_steps():
    allure = FakeAllure()

    with AllureBackend(allure).step("open the menu"):
        pass

    assert allure.steps == ["open the menu"]


def test_a_png_is_attached_as_an_image(tmp_path):
    """The extension decides whether a screenshot is shown or downloaded."""
    allure = FakeAllure()
    screenshot = tmp_path / "window.png"
    screenshot.write_bytes(b"x")

    AllureBackend(allure).attach_file("window", screenshot)

    source, name, attachment_type = allure.attach.files[0]
    assert source == str(screenshot)
    assert name == "window"
    assert attachment_type == "PNG"


def test_an_unknown_extension_is_still_attached(tmp_path):
    """No declared type still keeps the evidence in the report."""
    allure = FakeAllure()
    dump = tmp_path / "tree.uia"
    dump.write_text("dump", encoding="utf-8")

    AllureBackend(allure).attach_file("tree", dump)

    assert allure.attach.files[0][2] is None


def test_text_is_attached_as_text():
    allure = FakeAllure()

    AllureBackend(allure).attach_text("notes", "hello")

    assert allure.attach.bodies == [("hello", "notes", "TEXT")]
