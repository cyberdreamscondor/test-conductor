"""High-level checks over a running Chrome.

A bare `assert chrome.menu.has_item("Settings")` reports `assert False` when it
fails, which says nothing. These checks exist to produce a message that names
the expectation, the actual state, and enough context to diagnose it without
rerunning.

Four rules keep them small:

1. One check, one observable property. No check_everything_about_the_menu.
2. A check NEVER changes state. If check_menu_has_item opened the menu itself,
   there would be no way left to verify that the menu is closed. The test
   acts; the check only observes.
3. A check takes plain values, never a config object, so the framework stays
   independent of how a suite stores its data.
4. Compose in the test. Two readable calls beat one check with five flags.

For pytest to show its usual assertion introspection from inside this module,
a suite's conftest.py must register it before first import:

    pytest.register_assert_rewrite("chrome_checks")
"""

from __future__ import annotations

from collections.abc import Iterable

from chrome import Chrome
from chrome_menu import AppMenu

# --- browser ------------------------------------------------------------------


def check_browser_running(chrome: Chrome) -> None:
    """The browser process is alive."""
    assert chrome.is_running, (
        f"the browser process is not running (profile: {chrome.profile_directory})"
    )


def check_window_title_contains(chrome: Chrome, fragment: str) -> None:
    """The window title contains ``fragment``."""
    title = chrome.title
    assert fragment in title, f"window title {title!r} does not contain {fragment!r}"


def check_profile_isolated(chrome: Chrome, marker: str) -> None:
    """The browser is using a framework-managed throwaway profile."""
    profile = chrome.profile_directory
    assert profile.exists(), f"profile directory {profile} does not exist"
    assert marker in str(profile), (
        f"profile {profile} does not look framework-managed (expected {marker!r} in the path)"
    )


# --- application menu ---------------------------------------------------------


def check_menu_open(menu: AppMenu) -> None:
    """The application menu is displayed."""
    assert menu.is_open, "the application menu is not open"


def check_menu_closed(menu: AppMenu) -> None:
    """The application menu is not displayed."""
    names = menu.item_names()
    assert not names, f"the application menu is still open, showing {len(names)} items: {names}"


def check_menu_has_item(menu: AppMenu, label: str) -> None:
    """The menu offers an entry for ``label``, ignoring its accelerator."""
    assert menu.has_item(label), f"menu item {str(label)!r} not found. Present: {menu.item_names()}"


def check_menu_has_items(menu: AppMenu, labels: Iterable[str]) -> None:
    """The menu offers an entry for every one of ``labels``."""
    labels = list(labels)
    present = menu.item_names()
    missing = [str(label) for label in labels if not menu.has_item(label)]
    assert not missing, f"menu items {missing} not found. Present: {present}"
