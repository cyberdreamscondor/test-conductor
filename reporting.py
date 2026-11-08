from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_ALLURE_TYPE_BY_SUFFIX = {
    ".png": "PNG",
    ".jpg": "JPG",
    ".jpeg": "JPG",
    ".txt": "TEXT",
    ".log": "TEXT",
    ".html": "HTML",
    ".json": "JSON",
    ".xml": "XML",
    ".csv": "CSV",
}


class ReportBackend(Protocol):
    def step(self, name: str) -> AbstractContextManager[Any]: ...

    def attach_text(self, name: str, text: str) -> None: ...

    def attach_file(self, name: str, path: Path) -> None: ...


class NullBackend:
    def step(self, name: str) -> AbstractContextManager[Any]:
        """Do nothing, successfully."""
        return nullcontext()

    def attach_text(self, name: str, text: str) -> None:
        """Discard the attachment, recording that it happened."""
        logger.debug("attachment %r (%d chars) discarded: no report backend", name, len(text))

    def attach_file(self, name: str, path: Path) -> None:
        """Discard the attachment; the file stays where it was written."""
        logger.debug("attachment %r (%s) discarded: no report backend", name, path)


class AllureBackend:
    def __init__(self, allure_module: Any) -> None:
        self._allure = allure_module

    def _attachment_type(self, path: Path) -> Any:
        """The type that renders a file inline, or None if the suffix is new."""
        name = _ALLURE_TYPE_BY_SUFFIX.get(path.suffix.lower())
        if name is None:
            return None
        return getattr(self._allure.attachment_type, name, None)

    def step(self, name: str) -> AbstractContextManager[Any]:
        """An Allure step, which times itself and fails with its body."""
        return self._allure.step(name)

    def attach_text(self, name: str, text: str) -> None:
        """Attach text to the test currently running."""
        self._allure.attach(text, name=name, attachment_type=self._allure.attachment_type.TEXT)

    def attach_file(self, name: str, path: Path) -> None:
        """Attach a file by copying it into the results directory."""
        self._allure.attach.file(str(path), name=name, attachment_type=self._attachment_type(path))


_backend: ReportBackend | None = None


def _detect_backend() -> ReportBackend:
    """Use Allure when it is installed, and nothing when it is not."""
    try:
        import allure
    except ImportError:
        logger.debug("allure is not installed; steps and attachments go to the log only")
        return NullBackend()
    return AllureBackend(allure)


def backend() -> ReportBackend:
    """The active backend, detected on first use and remembered."""
    global _backend
    if _backend is None:
        _backend = _detect_backend()
    return _backend


def use_backend(new_backend: ReportBackend | None) -> None:
    """Install a backend, or None to go back to detection."""
    global _backend
    _backend = new_backend


@contextmanager
def step(name: str) -> Generator[None, None, None]:
    """Record that the framework is performing ``name``, in log and report."""
    logger.info("%s", name)
    with backend().step(name):
        yield


def attach_text(name: str, text: str) -> None:
    """Attach text to the running test's report."""
    backend().attach_text(name, text)


def attach_file(name: str, path: Path) -> None:
    """Attach an existing file to the running test's report."""
    backend().attach_file(name, path)
