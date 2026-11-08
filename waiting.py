from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
DEFAULT_INTERVAL = 0.2


class WaitTimeout(AssertionError):
    pass


def wait_until(
    condition: Callable[[], T | None],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
    description: str = "condition to become true",
    ignore: tuple[type[BaseException], ...] = (),
) -> T:
    """Poll ``condition`` until it returns something truthy, then return it."""
    if timeout <= 0:
        raise ValueError(f"timeout must be positive, got {timeout}")
    if interval <= 0:
        raise ValueError(f"interval must be positive, got {interval}")

    started = time.monotonic()
    deadline = started + timeout
    last_error: BaseException | None = None
    attempts = 0

    logger.debug("waiting for %s (timeout %.1fs)", description, timeout)

    while True:
        attempts += 1
        try:
            result = condition()
            if result:
                logger.debug(
                    "%s: satisfied after %.2fs (%d attempt(s))",
                    description,
                    time.monotonic() - started,
                    attempts,
                )
                return result
        except ignore as exc:  # noqa: B902 - the caller chose these types
            last_error = exc

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            message = (
                f"Timed out after {timeout:.1f}s ({attempts} attempts) waiting for {description}."
            )
            if last_error is not None:
                message += f" Last suppressed error: {last_error!r}"
            raise WaitTimeout(message)

        time.sleep(min(interval, remaining))
