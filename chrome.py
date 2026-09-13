"""The high-level entry point that autotests use.

This is the only name a test in chrome-tests should need::

    from chrome import Chrome

    with Chrome.launch() as browser:
        browser.menu.open()
        assert browser.menu.has_item("Settings")

Everything underneath - process control, UI Automation, window discovery,
waiting - is deliberately hidden. A test must never import pywinauto, comtypes
or a CDP client directly: the point of the framework is that swapping the
driver does not touch a single test.
"""

from __future__ import annotations

from chrome_config import ChromeConfig
from chrome_menu import AppMenu
from chrome_process import ChromeProcess
from chrome_window import ChromeWindow


class Chrome:
    """A running Chrome browser, driven as a Windows desktop application."""

    def __init__(self, process: ChromeProcess, window: ChromeWindow, config: ChromeConfig):
        self._process = process
        self._window = window
        self._config = config
        self._menu = AppMenu(window, timeout=config.ui_timeout)

    @classmethod
    def launch(cls, config: ChromeConfig | None = None, **overrides) -> Chrome:
        """Start Chrome and wait until its window is really there."""
        if config is None:
            config = ChromeConfig.detect(**overrides)
        elif overrides:
            config = config.with_changes(**overrides)

        process = ChromeProcess.launch(config)
        try:
            window = ChromeWindow.attach(process.pid, timeout=config.launch_timeout)
        except BaseException:
            # If the window never appears, the process is still running and
            # would be left behind as an orphan holding its profile directory.
            # Clean up before letting the failure propagate.
            process.terminate()
            raise

        return cls(process, window, config)

    @property
    def window(self) -> ChromeWindow:
        """The browser window: frame, toolbar, tab strip."""
        return self._window

    @property
    def menu(self) -> AppMenu:
        """The native three-dot application menu."""
        return self._menu

    @property
    def title(self) -> str:
        """The window title, e.g. 'about:blank - Google Chrome'."""
        return self._window.title

    @property
    def profile_directory(self):
        """The throwaway profile this browser was given."""
        return self._process.profile_directory

    @property
    def is_running(self) -> bool:
        """True while the browser process is alive."""
        return self._process.is_running

    def close(self) -> None:
        """Stop the browser and delete its profile. Safe to call twice."""
        self._process.terminate()

    def __enter__(self) -> Chrome:
        return self

    def __exit__(self, *exception_details: object) -> None:
        self.close()
