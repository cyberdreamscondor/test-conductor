from __future__ import annotations

import contextlib
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from chrome_config import ChromeConfig

logger = logging.getLogger(__name__)

PROFILE_PREFIX = "test-conductor-chrome-"


class ChromeProcess:
    def __init__(
        self, popen: subprocess.Popen, profile_directory: Path, config: ChromeConfig
    ) -> None:
        self._popen = popen
        self._profile_directory = profile_directory
        self._config = config
        self._terminated = False

    @classmethod
    def launch(cls, config: ChromeConfig) -> ChromeProcess:
        """Start Chrome against a fresh, empty profile directory."""
        profile_directory = Path(tempfile.mkdtemp(prefix=PROFILE_PREFIX))

        command = config.command_line(profile_directory)
        logger.info("launching chrome: %s", " ".join(command))
        popen = subprocess.Popen(command)
        logger.info("chrome started, pid=%s", popen.pid)
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

        logger.info(
            "terminating chrome pid=%s, profile=%s",
            self._popen.pid,
            self._profile_directory,
        )

        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(self._popen.pid)],
                capture_output=True,
                check=False,
            )
        else:
            self._popen.kill()

        with contextlib.suppress(subprocess.TimeoutExpired):
            self._popen.wait(timeout=10)

        shutil.rmtree(self._profile_directory, ignore_errors=True)
        logger.debug("profile directory removed: %s", self._profile_directory)

    def __enter__(self) -> ChromeProcess:
        return self

    def __exit__(self, *exception_details: object) -> None:
        self.terminate()
