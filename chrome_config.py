from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

CHROME_PATH_ENV_VAR = "TEST_CONDUCTOR_CHROME"

_WINDOWS_CANDIDATES = (
    r"{ProgramFiles}\Google\Chrome\Application\chrome.exe",
    r"{ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    r"{LOCALAPPDATA}\Google\Chrome\Application\chrome.exe",
)

_APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"

DEFAULT_LAUNCH_FLAGS = (
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-session-crashed-bubble",
)


class ChromeNotFoundError(FileNotFoundError):
    pass


def _registry_chrome_path() -> Path | None:
    """Ask Windows where chrome.exe is. Returns None on any failure."""
    if sys.platform != "win32":
        return None
    import winreg

    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, _APP_PATHS_KEY) as key:
                value, _ = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        candidate = Path(value)
        if candidate.is_file():
            return candidate
    return None


def find_chrome_executable(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Locate Chrome: explicit path, environment, registry, install dirs."""
    searched: list[str] = []

    if explicit is not None:
        candidate = Path(explicit)
        if candidate.is_file():
            return candidate
        raise ChromeNotFoundError(
            f"Chrome was explicitly set to {candidate}, which does not exist."
        )

    from_env = os.environ.get(CHROME_PATH_ENV_VAR)
    if from_env:
        candidate = Path(from_env)
        if candidate.is_file():
            return candidate
        raise ChromeNotFoundError(
            f"{CHROME_PATH_ENV_VAR} is set to {candidate}, which does not exist."
        )
    searched.append(f"${CHROME_PATH_ENV_VAR} (not set)")

    from_registry = _registry_chrome_path()
    if from_registry is not None:
        return from_registry
    searched.append(f"Windows registry: {_APP_PATHS_KEY}")

    for template in _WINDOWS_CANDIDATES:
        expanded = template.format_map(_EnvDefaults())
        searched.append(expanded)
        candidate = Path(expanded)
        if candidate.is_file():
            return candidate

    raise ChromeNotFoundError(
        "Could not find Google Chrome. Searched:\n  "
        + "\n  ".join(searched)
        + f"\nSet {CHROME_PATH_ENV_VAR} to the full path of chrome.exe."
    )


class _EnvDefaults(dict):
    def __missing__(self, key: str) -> str:
        return os.environ.get(key, "")


@dataclass(frozen=True)
class ChromeConfig:
    executable: Path

    launch_timeout: float = 30.0

    ui_timeout: float = 10.0

    extra_flags: tuple[str, ...] = ()

    remote_debugging_port: int | None = None

    initial_url: str = "about:blank"

    launch_flags: tuple[str, ...] = field(default=DEFAULT_LAUNCH_FLAGS)

    @classmethod
    def detect(
        cls, executable: str | os.PathLike[str] | None = None, **overrides: Any
    ) -> ChromeConfig:
        """Build a config, locating Chrome automatically unless told where."""
        return cls(executable=find_chrome_executable(executable), **overrides)

    def with_changes(self, **overrides: Any) -> ChromeConfig:
        """Return a copy with some fields replaced, leaving this one untouched."""
        return replace(self, **overrides)

    def command_line(self, profile_directory: str | os.PathLike[str]) -> list[str]:
        """Build the argv for launching Chrome against ``profile_directory``."""
        arguments = [
            str(self.executable),
            f"--user-data-dir={Path(profile_directory)}",
            *self.launch_flags,
        ]
        if self.remote_debugging_port is not None:
            arguments.append(f"--remote-debugging-port={self.remote_debugging_port}")
        arguments.extend(self.extra_flags)
        arguments.append(self.initial_url)
        return arguments
