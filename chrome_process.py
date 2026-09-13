"""Starting and stopping Chrome, with an isolated profile and no orphans.

This module owns the operating-system side of a browser: the process, its
throwaway profile directory, and making sure neither survives the test.

Two hazards it exists to prevent, both observed while spiking this layer:

* Driving the user's real browser. Every launch gets its own --user-data-dir,
  so automation can never touch real tabs, history or logins.
* Orphaned chrome.exe processes. Chrome spawns a tree of processes; killing
  only the one we started leaves children running, and they hold the profile
  directory open so the next run inherits a dirty environment.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from chrome_config import ChromeConfig

# Prefix for throwaway profile directories, so a leftover one is recognisable in
# the temp folder rather than looking like something important.
PROFILE_PREFIX = "test-conductor-chrome-"


class ChromeProcess:
    """A running Chrome, together with the temporary profile it was given."""

    def __init__(self, popen: subprocess.Popen, profile_directory: Path, config: ChromeConfig):
        self._popen = popen
        self._profile_directory = profile_directory
        self._config = config
        self._terminated = False

    @classmethod
    def launch(cls, config: ChromeConfig) -> ChromeProcess:
        """Start Chrome against a fresh, empty profile directory."""
        # mkdtemp, not a fixed path: parallel test runs must not share a
        # profile. Chrome locks its user-data-dir, so two browsers pointed at
        # one directory is a hard failure, not a subtle one.
        profile_directory = Path(tempfile.mkdtemp(prefix=PROFILE_PREFIX))

        popen = subprocess.Popen(config.command_line(profile_directory))
        return cls(popen, profile_directory, config)

    @property
    def pid(self) -> int:
        """Process id of the browser, which window lookups are scoped to."""
        return self._popen.pid

    @property
    def profile_directory(self) -> Path:
        """The throwaway profile this browser is using."""
        return self._profile_directory

    @property
    def is_running(self) -> bool:
        """True while the launched process is still alive."""
        return self._popen.poll() is None

    def terminate(self) -> None:
        """Stop Chrome and delete its profile. Safe to call more than once."""
        if self._terminated:
            return
        self._terminated = True

        if sys.platform == "win32":
            # /T kills the whole process tree, /F does not ask politely.
            # Chrome's renderer and GPU processes are children; without /T they
            # survive and keep holding the profile directory open.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(self._popen.pid)],
                capture_output=True,
                check=False,  # already-dead is a normal outcome, not an error
            )
        else:
            self._popen.kill()

        # Reap the process so it does not linger as a zombie. Best-effort: if it
        # will not exit there is nothing further we can do, and the profile
        # cleanup below must still be attempted. suppress() states that the
        # exception is deliberately ignored, where try/except/pass reads like
        # something someone forgot to finish.
        with contextlib.suppress(subprocess.TimeoutExpired):
            self._popen.wait(timeout=10)

        # ignore_errors: on Windows a file can stay locked briefly after the
        # process dies. A leftover temp directory is untidy; an exception here
        # would fail an otherwise passing test, which is much worse.
        shutil.rmtree(self._profile_directory, ignore_errors=True)

    def __enter__(self) -> ChromeProcess:
        return self

    def __exit__(self, *exception_details: object) -> None:
        self.terminate()
