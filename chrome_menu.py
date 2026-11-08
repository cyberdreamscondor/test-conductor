from __future__ import annotations

import logging
import re
from enum import StrEnum

from chrome_window import UIA_TRANSIENT_ERRORS, ChromeWindow, UIAElement
from reporting import step
from waiting import wait_until

logger = logging.getLogger(__name__)


class UnknownMenuItem(LookupError):
    pass


class MenuItem(StrEnum):
    NEW_TAB = "New tab"
    NEW_WINDOW = "New window"
    NEW_INCOGNITO_WINDOW = "New Incognito window"
    PASSWORDS_AND_AUTOFILL = "Passwords and autofill"
    HISTORY = "History"
    DOWNLOADS = "Downloads"
    BOOKMARKS_AND_LISTS = "Bookmarks and lists"
    TAB_GROUPS = "Tab groups"
    EXTENSIONS = "Extensions"
    DELETE_BROWSING_DATA = "Delete browsing data"
    ZOOM = "Zoom"
    FULL_SCREEN = "Full screen"
    PRINT = "Print"
    FIND_AND_EDIT = "Find and edit"
    CAST_SAVE_AND_SHARE = "Cast, save, and share"
    MORE_TOOLS = "More tools"
    HELP = "Help"
    SETTINGS = "Settings"
    EXIT = "Exit"


_MEMBER_NAME = re.compile(r"[A-Z][A-Z0-9_]*")


def _as_label(value: str) -> str:
    """Resolve a member, a member name or a literal into the displayed label."""
    text = str(value)
    try:
        return str(MenuItem[text])
    except KeyError:
        pass
    if _MEMBER_NAME.fullmatch(text):
        known = ", ".join(sorted(member.name for member in MenuItem))
        raise UnknownMenuItem(f"{text!r} is not a MenuItem name. Known names: {known}")
    return text


def _matches(item_name: str, label: str) -> bool:
    """Does a menu item named ``item_name`` mean ``label``, accelerator aside?"""
    label = _as_label(label)
    if item_name == label:
        return True
    if item_name.startswith(label):
        remainder = item_name[len(label) :]
        return not remainder[:1].isalnum()
    return False


class AppMenu:
    def __init__(self, window: ChromeWindow, timeout: float) -> None:
        self._window = window
        self._timeout = timeout

    def _items(self) -> list[UIAElement]:
        """Menu items currently in the tree; an empty list means closed."""
        try:
            return self._window.element.descendants(control_type="MenuItem")
        except UIA_TRANSIENT_ERRORS:
            return []

    @property
    def is_open(self) -> bool:
        """True while the menu is displayed."""
        return len(self._items()) > 0

    def item_names(self) -> list[str]:
        """Accessible names of the visible menu items, accelerators included."""
        names = []
        for item in self._items():
            try:
                names.append(item.element_info.name or "")
            except UIA_TRANSIENT_ERRORS:
                continue
        return names

    def has_item(self, label: str) -> bool:
        """Is there a menu item for ``label``? Accelerators are ignored."""
        return any(_matches(name, label) for name in self.item_names())

    def open(self) -> AppMenu:
        """Open the menu and wait until it really is open; a no-op if open."""
        if self.is_open:
            logger.debug("application menu is already open; not clicking again")
            return self

        with step("open the application menu"):
            with step("focus the browser window and click the menu button"):
                self._window.focus()
                self._window.app_menu_button(timeout=self._timeout).click_input()

            with step("wait for the menu items to appear"):
                wait_until(
                    lambda: self.is_open,
                    timeout=self._timeout,
                    description="Chrome's application menu to open",
                    ignore=UIA_TRANSIENT_ERRORS,
                )
            logger.info("application menu open with %d item(s)", len(self._items()))
        return self

    def close(self) -> AppMenu:
        """Close the menu with Escape and wait until it really is closed."""
        if not self.is_open:
            logger.debug("application menu is already closed")
            return self

        with step("close the application menu with Escape"):
            self._window.focus()
            self._window.element.type_keys("{ESC}")

            wait_until(
                lambda: not self.is_open,
                timeout=self._timeout,
                description="Chrome's application menu to close",
                ignore=UIA_TRANSIENT_ERRORS,
            )
        return self

    def click_item(self, label: str) -> None:
        """Click a menu item by label, opening the menu first if needed."""
        logger.debug("menu item %r resolves to %r", str(label), _as_label(label))

        with step(f"click the menu item {_as_label(label)!r}"):
            self.open()

            def matching_item() -> UIAElement | None:
                for item in self._items():
                    try:
                        if _matches(item.element_info.name or "", label):
                            return item
                    except UIA_TRANSIENT_ERRORS:
                        continue
                return None

            item = wait_until(
                matching_item,
                timeout=self._timeout,
                description=f"a menu item labelled {label!r}. Present: {self.item_names()}",
                ignore=UIA_TRANSIENT_ERRORS,
            )
            item.click_input()
