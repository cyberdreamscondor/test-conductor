"""Chrome's native application menu - the three-dot menu.

Measured facts that this module is built on:

* The menu is a CHILD of the browser window, not a separate top-level window.
  Older documentation claims otherwise; it is not true in current Chrome.
* The accessibility tree tracks open and closed correctly - 0 menu items
  before, 24 while open, 0 after Escape. That is what makes assertions about
  menu contents meaningful: such a test can genuinely fail.
* Item names embed their keyboard accelerator: 'New tab Ctrl+T',
  'Delete browsing data... Ctrl+Shift+Del'. Exact matching on a plain label
  would therefore never match, which is why `has_item` is prefix-based.
"""

from __future__ import annotations

from enum import StrEnum

from chrome_window import UIA_TRANSIENT_ERRORS, ChromeWindow
from waiting import wait_until


class MenuItem(StrEnum):
    """Entries of Chrome's application menu, by logical name."""

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


def _matches(item_name: str, label: str) -> bool:
    """Does a menu item named ``item_name`` mean ``label``, accelerator aside?"""
    if item_name == label:
        return True
    if item_name.startswith(label):
        remainder = item_name[len(label) :]
        return not remainder[:1].isalnum()
    return False


class AppMenu:
    """The three-dot menu of one Chrome window."""

    def __init__(self, window: ChromeWindow, timeout: float):
        self._window = window
        self._timeout = timeout

    def _items(self) -> list:
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
            return self

        # Focus first. A click is delivered to a screen coordinate, so an
        # overlapping window would swallow it silently - no error, no menu.
        self._window.focus()
        self._window.app_menu_button(timeout=self._timeout).click_input()

        wait_until(
            lambda: self.is_open,
            timeout=self._timeout,
            description="Chrome's application menu to open",
            ignore=UIA_TRANSIENT_ERRORS,
        )
        return self

    def close(self) -> AppMenu:
        """Close the menu with Escape and wait until it really is closed."""
        if not self.is_open:
            return self

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
        self.open()

        def matching_item():
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
