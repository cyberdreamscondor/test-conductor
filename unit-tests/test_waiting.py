import time

import pytest

from waiting import WaitTimeout, wait_until


def test_returns_the_conditions_value_not_just_true():
    """The value is returned, so a lookup and its wait are one expression."""
    result = wait_until(lambda: "the window", timeout=1)
    assert result == "the window"


def test_returns_as_soon_as_the_condition_becomes_true():
    """A satisfiable condition must not wait out the timeout."""
    attempts = []

    def ready_on_third_attempt():
        attempts.append(1)
        return len(attempts) >= 3

    started = time.monotonic()
    wait_until(ready_on_third_attempt, timeout=5, interval=0.01)
    elapsed = time.monotonic() - started

    assert len(attempts) == 3
    assert elapsed < 1.0, "returned late; it waited longer than the condition needed"


def test_raises_wait_timeout_when_the_condition_never_holds():
    """A wait that never succeeds must fail loudly, naming what it waited for."""
    with pytest.raises(WaitTimeout) as failure:
        wait_until(lambda: False, timeout=0.1, interval=0.01, description="the app menu")

    assert "the app menu" in str(failure.value)


def test_wait_timeout_is_an_assertion_error():
    """An unmet expectation, not infrastructure trouble."""
    assert issubclass(WaitTimeout, AssertionError)


def test_condition_is_evaluated_at_least_once():
    """Guards an off-by-one where a very short timeout tests nothing."""
    calls = []

    with pytest.raises(WaitTimeout):
        wait_until(lambda: calls.append(1), timeout=0.001, interval=0.01)

    assert len(calls) >= 1


def test_ignored_exceptions_are_retried():
    """Querying a half-built UIA tree raises; that means 'not ready'."""
    attempts = []

    def raises_twice_then_succeeds():
        attempts.append(1)
        if len(attempts) < 3:
            raise KeyError("tree not built yet")
        return "ready"

    result = wait_until(
        raises_twice_then_succeeds,
        timeout=5,
        interval=0.01,
        ignore=(KeyError,),
    )
    assert result == "ready"


def test_unlisted_exceptions_propagate_immediately():
    """Swallowing everything would turn a typo into a misleading timeout."""

    def has_a_bug():
        raise AttributeError("typo in an attribute name")

    with pytest.raises(AttributeError):
        wait_until(has_a_bug, timeout=5, interval=0.01, ignore=(KeyError,))


def test_the_last_suppressed_error_appears_in_the_timeout_message():
    """The suppressed error is usually the real explanation."""

    def always_raises():
        raise KeyError("element not found")

    with pytest.raises(WaitTimeout) as failure:
        wait_until(always_raises, timeout=0.05, interval=0.01, ignore=(KeyError,))

    assert "element not found" in str(failure.value)


def test_does_not_overshoot_the_deadline():
    """An interval longer than the remaining time must not extend the wait."""
    started = time.monotonic()

    with pytest.raises(WaitTimeout):
        wait_until(lambda: False, timeout=0.1, interval=5.0)

    elapsed = time.monotonic() - started
    assert elapsed < 1.0, f"overshot the deadline: took {elapsed:.2f}s for a 0.1s timeout"


@pytest.mark.parametrize("bad_value", [0, -1])
def test_rejects_non_positive_timeout_and_interval(bad_value):
    """timeout=0 would never poll and interval=0 would spin the CPU."""
    with pytest.raises(ValueError):
        wait_until(lambda: True, timeout=bad_value)

    with pytest.raises(ValueError):
        wait_until(lambda: True, interval=bad_value)
