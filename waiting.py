from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

DEFAULT_TIMEOUT = 10.0
DEFAULT_INTERVAL = 0.2


class WaitTimeout(AssertionError):
    """A condition never became true within its deadline."""


def wait_until(
    condition: Callable[[], T],
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

    deadline = time.monotonic() + timeout
    last_error: BaseException | None = None
    attempts = 0

    while True:
        attempts += 1
        try:
            result = condition()
            if result:
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
