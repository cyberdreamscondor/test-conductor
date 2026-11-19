import pytest
from pywinauto.uia_defines import NoPatternInterfaceError

from chrome_menu import MenuItem, UnknownMenuItem, _matches, activate


class FakeItem:
    """A menu item that records how it was asked to act."""

    def __init__(self, invoke_error=None):
        self.invoked = False
        self.clicked = False
        self._invoke_error = invoke_error

    def invoke(self):
        if self._invoke_error is not None:
            raise self._invoke_error
        self.invoked = True

    def click_input(self):
        self.clicked = True


def test_a_menu_item_is_invoked_rather_than_clicked():
    """Settings sits at y=1077; a 1024x768 desktop has nothing to click."""
    item = FakeItem()

    activate(item)

    assert item.invoked
    assert not item.clicked


def test_an_item_without_the_invoke_pattern_is_clicked():
    """Not every control implements Invoke, and a click still works locally."""
    item = FakeItem(invoke_error=NoPatternInterfaceError())

    activate(item)

    assert item.clicked


def test_a_member_matches_its_label():
    """A StrEnum member is a str, so it needs no translation."""
    assert _matches("Settings", MenuItem.SETTINGS)


def test_a_member_name_matches_the_label():
    """YAML delivers "SETTINGS" while the displayed label is "Settings"."""
    assert _matches("Settings", "SETTINGS")


def test_a_literal_label_still_works():
    """A one-off label must not require adding an enum member."""
    assert _matches("Settings", "Settings")


def test_a_name_matches_a_label_that_carries_an_accelerator():
    """Name resolution and accelerator stripping on the same lookup."""
    assert _matches("New tab Ctrl+T", "NEW_TAB")


def test_a_misspelt_member_name_is_an_error_not_a_label():
    """A typo must blame the config, not report Chrome as missing an entry."""
    with pytest.raises(UnknownMenuItem) as failure:
        _matches("Settings", "SETINGS")

    message = str(failure.value)
    assert "SETINGS" in message
    assert "SETTINGS" in message, "the error should list the valid names"


def test_unknown_menu_item_is_a_lookup_error():
    """A LookupError blames the test or config, not the application."""
    assert issubclass(UnknownMenuItem, LookupError)


def test_ordinary_text_is_never_mistaken_for_a_member_name():
    """An absent normal label is a mismatch, not a bad member name."""
    assert not _matches("Settings", "Bookmark manager")


def test_a_bare_prefix_also_matches_which_is_a_known_limitation():
    """A bare prefix matches, since the accelerator rule accepts any space."""
    assert _matches("New tab Ctrl+T", "New")
