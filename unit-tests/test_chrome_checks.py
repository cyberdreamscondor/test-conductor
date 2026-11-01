"""Unit tests for the high-level checks.

No Chrome: the checks only read a small surface (is_running, title,
profile_directory, is_open, item_names, has_item), so stubs stand in for the
real objects. That means these tests also pin down that surface - if a check
starts reaching for something else, it will not work against a stub.

Most of these assert on the FAILURE MESSAGE. That is the whole reason the
checks exist, so it is the thing worth protecting.
"""

from pathlib import Path

import pytest

from chrome_checks import (
    check_browser_running,
    check_menu_closed,
    check_menu_has_item,
    check_menu_has_items,
    check_menu_open,
    check_profile_isolated,
    check_window_title_contains,
)
from chrome_menu import MenuItem, _matches


class FakeMenu:
    """Stands in for AppMenu. Mirrors the real matching rules."""

    def __init__(self, names):
        self._names = list(names)

    def item_names(self):
        return list(self._names)

    @property
    def is_open(self):
        return bool(self._names)

    def has_item(self, label):
        return any(_matches(name, label) for name in self._names)


class FakeChrome:
    def __init__(self, running=True, title="about:blank - Google Chrome", profile=None):
        self.is_running = running
        self.title = title
        self.profile_directory = profile or Path("/tmp/test-conductor-chrome-abc")


# --- browser ------------------------------------------------------------------


def test_running_browser_passes():
    check_browser_running(FakeChrome(running=True))


def test_dead_browser_fails_and_names_the_profile():
    """The profile path is the handle for finding leftover files or a crash log."""
    with pytest.raises(AssertionError) as failure:
        check_browser_running(FakeChrome(running=False))

    assert "not running" in str(failure.value)
    assert "test-conductor-chrome-abc" in str(failure.value)


def test_title_check_reports_both_sides():
    """The actual title is needed to tell a wrong page from a slow one."""
    with pytest.raises(AssertionError) as failure:
        check_window_title_contains(FakeChrome(title="New Tab"), "Google Chrome")

    message = str(failure.value)
    assert "New Tab" in message
    assert "Google Chrome" in message


def test_profile_isolation_rejects_a_foreign_profile():
    """An unmarked profile may mean the user's real browser data."""
    with pytest.raises(AssertionError) as failure:
        check_profile_isolated(FakeChrome(profile=Path.home()), "test-conductor")

    assert "framework-managed" in str(failure.value)


def test_profile_isolation_rejects_a_missing_directory():
    with pytest.raises(AssertionError) as failure:
        check_profile_isolated(FakeChrome(profile=Path("/no/such/dir")), "test-conductor")

    assert "does not exist" in str(failure.value)


# --- menu ---------------------------------------------------------------------


def test_open_menu_passes():
    check_menu_open(FakeMenu(["Settings"]))


def test_closed_menu_fails_check_menu_open():
    with pytest.raises(AssertionError) as failure:
        check_menu_open(FakeMenu([]))

    assert "not open" in str(failure.value)


def test_closed_menu_passes_check_menu_closed():
    check_menu_closed(FakeMenu([]))


def test_check_menu_closed_lists_the_leftover_items():
    """What is still showing distinguishes 'never closed' from 'reopened'."""
    with pytest.raises(AssertionError) as failure:
        check_menu_closed(FakeMenu(["New tab Ctrl+T", "Settings"]))

    message = str(failure.value)
    assert "still open" in message
    assert "Settings" in message


def test_has_item_accepts_a_menu_item_enum():
    """A StrEnum member passes straight through as its label."""
    check_menu_has_item(FakeMenu(["Settings"]), MenuItem.SETTINGS)


def test_has_item_accepts_a_plain_string():
    """A label with no enum member yet must still work."""
    check_menu_has_item(FakeMenu(["Some Exotic Entry"]), "Some Exotic Entry")


def test_has_item_ignores_the_accelerator():
    """Chrome's real name is 'New tab Ctrl+T', so the label must still match."""
    check_menu_has_item(FakeMenu(["New tab Ctrl+T"]), MenuItem.NEW_TAB)


def test_missing_item_failure_lists_what_is_present():
    """Shows at once whether an entry was renamed or the menu never opened."""
    with pytest.raises(AssertionError) as failure:
        check_menu_has_item(FakeMenu(["New tab Ctrl+T", "History"]), MenuItem.SETTINGS)

    message = str(failure.value)
    assert "Settings" in message
    assert "History" in message, "the message should list the items that ARE there"


def test_has_items_reports_every_missing_entry_at_once():
    """All missing entries in one run, not one rerun per item."""
    menu = FakeMenu(["New tab Ctrl+T", "History"])

    with pytest.raises(AssertionError) as failure:
        check_menu_has_items(menu, [MenuItem.NEW_TAB, MenuItem.SETTINGS, MenuItem.DOWNLOADS])

    message = str(failure.value)
    assert "Settings" in message
    assert "Downloads" in message
    assert "New tab" not in message.split("Present:")[0], "present items must not be listed missing"


def test_has_items_passes_when_all_are_present():
    menu = FakeMenu(["New tab Ctrl+T", "History", "Settings"])
    check_menu_has_items(menu, [MenuItem.NEW_TAB, MenuItem.HISTORY, MenuItem.SETTINGS])


def test_menu_item_lookup_by_name_rejects_a_typo():
    """A typo in a config name must fail, not become a literal label."""
    assert MenuItem["SETTINGS"] is MenuItem.SETTINGS

    with pytest.raises(KeyError):
        MenuItem["SETTINS"]
