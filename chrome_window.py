"""Chrome's native window: the frame, the toolbar, the tab strip.

This is the UI Automation half of the framework. It reads Chrome as a Windows
application through the accessibility tree that screen readers use.

What it can see: the window frame, toolbar buttons, the omnibox, the tab strip,
menus. What it CANNOT see: anything inside a tab. A whole web page collapses to
a single opaque node - measured, a fresh window exposes 39 elements in total.
Reading page content needs the DevTools protocol instead.

Windows-only by nature: UI Automation is a Windows API.
"""

from __future__ import annotations

from comtypes import COMError
from pywinauto import Desktop
from pywinauto.findwindows import ElementAmbiguousError, ElementNotFoundError

from waiting import wait_until

# Exceptions that mean "the tree is still settling", not "something is wrong".
# The accessibility tree is built lazily and elements can disappear between
# being listed and being read, so these are retried rather than raised.
UIA_TRANSIENT_ERRORS = (ElementNotFoundError, ElementAmbiguousError, COMError)

# The Chromium window class. NOT a way to identify Chrome: VS Code, Docker
# Desktop, Slack and every other Electron application use it too. Only ever
# used together with a process id.
CHROMIUM_WINDOW_CLASS = "Chrome_WidgetWin_1"

# The three-dot menu button. Matched by class name because that is the most
# stable of the three identifiers UIA offers:
#   class_name    'BrowserAppMenuButton'  semantic, not translated  <- use this
#   automation_id 'view_1007'             a bare sequence number, may shift
#   name          'Chrome'                translated into the UI language
# Note the name is 'Chrome' in current versions, not the
# 'Customize and control Google Chrome' that older documentation still cites.
APP_MENU_BUTTON_CLASS = "BrowserAppMenuButton"


def _candidate_windows(process_id: int) -> list:
    """Top-level Chrome windows belonging to one process."""
    found = []
    for window in Desktop(backend="uia").windows():
        try:
            info = window.element_info
            if info.process_id != process_id:
                continue
            if info.class_name != CHROMIUM_WINDOW_CLASS:
                continue
            if not info.name:
                continue  # unnamed windows are tooltips and popups, not the frame
            found.append(window)
        except UIA_TRANSIENT_ERRORS:
            continue  # element vanished mid-enumeration; simply skip it
    return found


class ChromeWindow:
    """One Chrome browser window, seen through UI Automation."""

    def __init__(self, element):
        self._element = element

    @classmethod
    def attach(cls, process_id: int, timeout: float) -> ChromeWindow:
        """Wait for the browser window of ``process_id`` and wrap it."""

        def largest_window():
            windows = _candidate_windows(process_id)
            if not windows:
                return None
            # A process can own several windows. The browser frame is the big
            # one; the others are popups and tooltips.
            return max(windows, key=lambda w: w.rectangle().width() * w.rectangle().height())

        element = wait_until(
            largest_window,
            timeout=timeout,
            description=f"the Chrome window of process {process_id}",
            ignore=UIA_TRANSIENT_ERRORS,
        )
        return cls(element)

    @property
    def element(self):
        """The underlying pywinauto wrapper."""
        return self._element

    @property
    def title(self) -> str:
        """The window title, e.g. 'about:blank - Google Chrome'."""
        return self._element.element_info.name or ""

    def focus(self) -> None:
        """Bring this window to the front, as mouse interaction requires."""
        self._element.set_focus()

    def button(self, class_name: str, timeout: float):
        """Find a toolbar button by its UIA class name, waiting for it."""

        def matching_button():
            for candidate in self._element.descendants(control_type="Button"):
                try:
                    if candidate.element_info.class_name == class_name:
                        return candidate
                except UIA_TRANSIENT_ERRORS:
                    continue
            return None

        return wait_until(
            matching_button,
            timeout=timeout,
            description=f"a Button with class {class_name!r}",
            ignore=UIA_TRANSIENT_ERRORS,
        )

    def app_menu_button(self, timeout: float):
        """The three-dot button that opens Chrome's application menu."""
        return self.button(APP_MENU_BUTTON_CLASS, timeout=timeout)
