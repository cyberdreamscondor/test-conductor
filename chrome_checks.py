from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from reporting import attach_text, step


class Browser(Protocol):
    @property
    def is_running(self) -> bool: ...

    @property
    def title(self) -> str: ...

    @property
    def profile_directory(self) -> Path: ...


class Menu(Protocol):
    @property
    def is_open(self) -> bool: ...

    def item_names(self) -> list[str]: ...

    def has_item(self, label: str) -> bool: ...


def check_browser_running(chrome: Browser) -> None:
    """The browser process is alive."""
    with step("check the browser process is running"):
        assert chrome.is_running, (
            f"the browser process is not running (profile: {chrome.profile_directory})"
        )


def check_window_title_contains(chrome: Browser, fragment: str) -> None:
    """The window title contains ``fragment``."""
    with step(f"check the window title contains {fragment!r}"):
        title = chrome.title
        assert fragment in title, f"window title {title!r} does not contain {fragment!r}"


def check_profile_isolated(chrome: Browser, marker: str) -> None:
    """The browser is using a framework-managed throwaway profile."""
    with step(f"check the profile directory is framework-managed ({marker!r})"):
        profile = chrome.profile_directory
        assert profile.exists(), f"profile directory {profile} does not exist"
        assert marker in str(profile), (
            f"profile {profile} does not look framework-managed (expected {marker!r} in the path)"
        )


def check_menu_open(menu: Menu) -> None:
    """The application menu is displayed."""
    with step("check the application menu is open"):
        assert menu.is_open, "the application menu is not open"


def check_menu_closed(menu: Menu) -> None:
    """The application menu is not displayed."""
    with step("check the application menu is closed"):
        names = menu.item_names()
        assert not names, f"the application menu is still open, showing {len(names)} items: {names}"


def check_menu_has_item(menu: Menu, label: str) -> None:
    """The menu offers an entry for ``label``, ignoring its accelerator."""
    with step(f"check the menu offers {str(label)!r}"):
        assert menu.has_item(label), (
            f"menu item {str(label)!r} not found. Present: {menu.item_names()}"
        )


def check_menu_has_items(menu: Menu, labels: Iterable[str]) -> None:
    """The menu offers an entry for every one of ``labels``."""
    labels = list(labels)
    with step(f"check the menu offers all {len(labels)} expected entries"):
        present = menu.item_names()
        missing = [str(label) for label in labels if not menu.has_item(label)]
        attach_text("menu items present", "\n".join(present) or "(the menu showed no items)")
        assert not missing, f"menu items {missing} not found. Present: {present}"
