"""Where Chrome is, how it should be launched, and how long to wait for it.
One place for every decision about starting a browser.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

# Environment variable that overrides executable discovery. CI machines and
# Linux checkouts will not have Chrome where Windows installers put it, and a
# developer may want to test against Chrome Beta or Canary without editing code.
CHROME_PATH_ENV_VAR = "TEST_CONDUCTOR_CHROME"

# Standard Windows install locations, in the order Chrome installers use them.
# Per-machine installs land in Program Files; per-user installs in LOCALAPPDATA.
_WINDOWS_CANDIDATES = (
    r"{ProgramFiles}\Google\Chrome\Application\chrome.exe",
    r"{ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    r"{LOCALAPPDATA}\Google\Chrome\Application\chrome.exe",
)

# Registry key Windows itself uses to resolve "chrome.exe" typed into Run.
# More reliable than guessing directories, because it survives non-default
# install locations - but it is Windows-only, hence the platform guard below.
_APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"

# Flags applied to every launch. Each one suppresses a first-run interruption
# that would otherwise sit on top of the UI the test is trying to read.
DEFAULT_LAUNCH_FLAGS = (
    "--no-first-run",  # skip the welcome/onboarding flow
    "--no-default-browser-check",  # skip "make Chrome your default browser?"
    "--disable-session-crashed-bubble",  # skip "Chrome didn't shut down correctly"
)


class ChromeNotFoundError(FileNotFoundError):
    """No Google Chrome executable could be located."""


def _registry_chrome_path() -> Path | None:
    """Ask Windows where chrome.exe is. Returns None on any failure."""
    if sys.platform != "win32":
        return None
    import winreg  # imported lazily: the module does not exist on Linux

    # Check both hives: per-machine installs write HKLM, per-user ones HKCU.
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, _APP_PATHS_KEY) as key:
                value, _ = winreg.QueryValueEx(key, "")  # "" is the default value
        except OSError:
            continue  # key absent in this hive - normal, try the next
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
        # An explicit path that does not exist is a mistake worth reporting at
        # once, rather than silently falling back to some other Chrome and
        # leaving the user wondering why their override did nothing.
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
        # Templates reference environment variables that may be absent on
        # non-Windows platforms; an unexpanded template can never be a file, so
        # a missing variable degrades harmlessly into "not found".
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
    """str.format_map source that yields an empty string for unset variables,"""

    def __missing__(self, key: str) -> str:
        return os.environ.get(key, "")


@dataclass(frozen=True)
class ChromeConfig:
    """Everything needed to start and drive one Chrome instance."""

    executable: Path
    """Full path to chrome.exe."""

    launch_timeout: float = 30.0
    """Seconds to wait for Chrome's window to appear in the accessibility tree.
    Generous: a cold start on a loaded machine is genuinely slow, and the cost
    of a high ceiling is zero when things are healthy - waits return early."""

    ui_timeout: float = 10.0
    """Seconds to wait for an element or a menu. Much shorter than launch: once
    Chrome is running, anything slower than this is a real failure."""

    extra_flags: tuple[str, ...] = ()
    """Additional command-line flags, appended after the defaults."""

    remote_debugging_port: int | None = None
    """Port for the DevTools protocol, or None to launch without it.

    Chrome only speaks CDP if it was STARTED with --remote-debugging-port; it
    cannot be enabled later. So whether page content will be readable is decided
    here, at launch, before any test runs - see the two-channel design in
    project docs/chrome-uia-findings.md."""

    initial_url: str = "about:blank"
    """Page to open on startup. Defaults to about:blank so a launch needs no
    network and cannot be slowed down by a remote site."""

    launch_flags: tuple[str, ...] = field(default=DEFAULT_LAUNCH_FLAGS)
    """Baseline flags. Overridable, but the defaults exist for good reasons -
    each suppresses a first-run dialog that would cover the UI under test."""

    @classmethod
    def detect(cls, executable: str | os.PathLike[str] | None = None, **overrides) -> ChromeConfig:
        """Build a config, locating Chrome automatically unless told where."""
        return cls(executable=find_chrome_executable(executable), **overrides)

    def with_changes(self, **overrides) -> ChromeConfig:
        """Return a copy with some fields replaced, leaving this one untouched."""
        return replace(self, **overrides)

    def command_line(self, profile_directory: str | os.PathLike[str]) -> list[str]:
        """Build the argv for launching Chrome against ``profile_directory``."""
        arguments = [
            str(self.executable),
            # Isolation. This single flag is what keeps automation away from the
            # user's real browser, so it is not optional and not overridable.
            f"--user-data-dir={Path(profile_directory)}",
            *self.launch_flags,
        ]
        if self.remote_debugging_port is not None:
            arguments.append(f"--remote-debugging-port={self.remote_debugging_port}")
        arguments.extend(self.extra_flags)
        arguments.append(self.initial_url)
        return arguments
