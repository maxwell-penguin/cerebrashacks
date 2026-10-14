import threading

import pytest

from cerebras_client import CircuitBreaker, CircuitBreakerOpen


class Probe:
    """Counts calls under a lock; raises when `fail` is set."""

    def __init__(self):
        self._lock = threading.Lock()
        self.calls = 0
        self.fail = True

    def __call__(self):
        with self._lock:
            self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        return "ok"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def trip(breaker, probe, n=3):
    for _ in range(n):
        with pytest.raises(RuntimeError):
            breaker.call(probe)


@pytest.fixture
def setup():
    clock, probe = Clock(), Probe()
    return CircuitBreaker(failure_threshold=3, recovery_timeout=30.0, clock=clock), probe, clock


def test_starts_closed(setup):
    breaker, _, _ = setup
    assert breaker.state == CircuitBreaker.CLOSED


def test_trips_open_after_threshold(setup):
    breaker, probe, _ = setup
    trip(breaker, probe, 2)
    assert breaker.state == CircuitBreaker.CLOSED
    trip(breaker, probe, 1)
    assert breaker.state == CircuitBreaker.OPEN


def test_open_rejects_without_calling_fn(setup):
    breaker, probe, _ = setup
    trip(breaker, probe)
    with pytest.raises(CircuitBreakerOpen):
        breaker.call(probe)
    assert probe.calls == 3


def test_half_open_after_timeout_lets_one_call_through(setup):
    breaker, probe, clock = setup
    trip(breaker, probe)
    clock.now = 30.0
    seen = []
    probe.fail = False

    def slow_probe():
        seen.append(breaker.state)
        with pytest.raises(CircuitBreakerOpen):  # a second caller during the probe is rejected
            breaker.call(probe)
        return probe()

    assert breaker.call(slow_probe) == "ok"
    assert seen == [CircuitBreaker.HALF_OPEN]
    assert probe.calls == 4  # 3 failures + exactly one probe


def test_half_open_success_closes(setup):
    breaker, probe, clock = setup
    trip(breaker, probe)
    clock.now = 30.0
    probe.fail = False
    breaker.call(probe)
    assert breaker.state == CircuitBreaker.CLOSED
    breaker.call(probe)  # and traffic flows again
    assert probe.calls == 5


def test_half_open_failure_reopens(setup):
    breaker, probe, clock = setup
    trip(breaker, probe)
    clock.now = 30.0
    with pytest.raises(RuntimeError):
        breaker.call(probe)
    assert breaker.state == CircuitBreaker.OPEN
    with pytest.raises(CircuitBreakerOpen):  # timeout restarts from the failed probe
        breaker.call(probe)
