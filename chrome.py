from __future__ import annotations

from pathlib import Path
from typing import Any

from chrome_config import ChromeConfig
from chrome_menu import AppMenu
from chrome_process import ChromeProcess
from chrome_window import ChromeWindow
from reporting import step


class Chrome:
    def __init__(self, process: ChromeProcess, window: ChromeWindow, config: ChromeConfig) -> None:
        self._process = process
        self._window = window
        self._config = config
        self._menu = AppMenu(window, timeout=config.ui_timeout)

    @classmethod
    def launch(cls, config: ChromeConfig | None = None, **overrides: Any) -> Chrome:
        """Start Chrome and wait until its window is really there."""
        if config is None:
            config = ChromeConfig.detect(**overrides)
        elif overrides:
            config = config.with_changes(**overrides)

        with step("launch Chrome"):
            process = ChromeProcess.launch(config)
            try:
                with step("attach to the Chrome window"):
                    window = ChromeWindow.attach(process.pid, timeout=config.launch_timeout)
            except BaseException:
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
    def profile_directory(self) -> Path:
        """The throwaway profile this browser was given."""
        return self._process.profile_directory

    @property
    def is_running(self) -> bool:
        """True while the browser process is alive."""
        return self._process.is_running

    def close(self) -> None:
        """Stop the browser and delete its profile. Safe to call twice."""
        with step("close Chrome"):
            self._process.terminate()

    def __enter__(self) -> Chrome:
        return self

    def __exit__(self, *exception_details: object) -> None:
        self.close()
