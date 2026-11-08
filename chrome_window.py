from __future__ import annotations

import logging
from typing import Any, TypeAlias

from comtypes import COMError
from pywinauto import Desktop
from pywinauto.findwindows import ElementAmbiguousError, ElementNotFoundError

from waiting import wait_until

logger = logging.getLogger(__name__)

UIA_TRANSIENT_ERRORS = (ElementNotFoundError, ElementAmbiguousError, COMError)

CHROMIUM_WINDOW_CLASS = "Chrome_WidgetWin_1"

APP_MENU_BUTTON_CLASS = "BrowserAppMenuButton"

UIAElement: TypeAlias = Any


def _candidate_windows(process_id: int) -> list[UIAElement]:
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
                continue
            found.append(window)
        except UIA_TRANSIENT_ERRORS:
            continue
    return found


def _window_area(window: UIAElement) -> int:
    """Screen area of a window, used to pick the frame from its popups."""
    rectangle = window.rectangle()
    return rectangle.width() * rectangle.height()


class ChromeWindow:
    def __init__(self, element: UIAElement) -> None:
        self._element = element

    @classmethod
    def attach(cls, process_id: int, timeout: float) -> ChromeWindow:
        """Wait for the browser window of ``process_id`` and wrap it."""

        def largest_window() -> UIAElement | None:
            windows = _candidate_windows(process_id)
            if not windows:
                return None
            return max(windows, key=_window_area)

        element = wait_until(
            largest_window,
            timeout=timeout,
            description=f"the Chrome window of process {process_id}",
            ignore=UIA_TRANSIENT_ERRORS,
        )
        logger.info("window attached: pid=%s title=%r", process_id, element.element_info.name)
        return cls(element)

    @property
    def element(self) -> UIAElement:
        """The underlying pywinauto wrapper."""
        return self._element

    @property
    def title(self) -> str:
        """The window title, e.g. 'about:blank - Google Chrome'."""
        return self._element.element_info.name or ""

    def focus(self) -> None:
        """Bring this window to the front, as mouse interaction requires."""
        logger.debug("focusing window %r", self.title)
        self._element.set_focus()

    def button(self, class_name: str, timeout: float) -> UIAElement:
        """Find a toolbar button by its UIA class name, waiting for it."""
        logger.debug("looking for a Button with class %r", class_name)

        def matching_button() -> UIAElement | None:
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

    def app_menu_button(self, timeout: float) -> UIAElement:
        """The three-dot button that opens Chrome's application menu."""
        return self.button(APP_MENU_BUTTON_CLASS, timeout=timeout)
