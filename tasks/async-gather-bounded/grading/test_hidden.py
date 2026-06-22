"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These fail against the NotImplementedError stub and pass only with a
correct bounded-concurrency implementation.

Concurrency is checked WITHOUT timing: each coroutine increments a shared
counter on entry, yields control once via ``asyncio.sleep(0)`` so siblings get
scheduled, records the peak observed in-flight count, then decrements. A correct
``limit``-bounded scheduler never lets the peak exceed ``limit``.
"""

import asyncio

import pytest

from asynckit import gather_bounded


class Tracker:
    def __init__(self):
        self.current = 0
        self.peak = 0


def _factory(tracker, value, hops=3):
    async def run():
        tracker.current += 1
        tracker.peak = max(tracker.peak, tracker.current)
        # Yield control several times so that, if the scheduler allowed it,
        # more than `limit` coroutines would overlap and bump the peak.
        for _ in range(hops):
            await asyncio.sleep(0)
        tracker.current -= 1
        return value

    return run


def test_results_in_input_order():
    tracker = Tracker()
    factories = [_factory(tracker, v) for v in [10, 20, 30, 40, 50]]
    result = asyncio.run(gather_bounded(factories, limit=2))
    assert result == [10, 20, 30, 40, 50]


def test_peak_concurrency_never_exceeds_limit():
    tracker = Tracker()
    factories = [_factory(tracker, v) for v in range(12)]
    result = asyncio.run(gather_bounded(factories, limit=3))
    assert result == list(range(12))
    assert tracker.peak <= 3
    assert tracker.peak >= 1


def test_limit_one_is_fully_serial():
    tracker = Tracker()
    factories = [_factory(tracker, v) for v in range(6)]
    result = asyncio.run(gather_bounded(factories, limit=1))
    assert result == list(range(6))
    assert tracker.peak == 1


def test_first_exception_propagates():
    tracker = Tracker()

    def boom_factory():
        async def run():
            tracker.current += 1
            tracker.peak = max(tracker.peak, tracker.current)
            await asyncio.sleep(0)
            tracker.current -= 1
            raise ValueError("boom")

        return run

    factories = [
        _factory(tracker, 1),
        boom_factory(),
        _factory(tracker, 3),
    ]
    with pytest.raises(ValueError, match="boom"):
        asyncio.run(gather_bounded(factories, limit=2))


def test_empty_list_returns_empty():
    assert asyncio.run(gather_bounded([], limit=4)) == []


def test_limit_greater_than_length():
    tracker = Tracker()
    factories = [_factory(tracker, v) for v in [7, 8, 9]]
    result = asyncio.run(gather_bounded(factories, limit=10))
    assert result == [7, 8, 9]
    assert tracker.peak <= 3


def test_results_input_order_with_varied_speeds():
    # Mixed completion speeds: a collector that appends in COMPLETION order would
    # reorder these; the result must follow INPUT order.
    tracker = Tracker()
    factories = [
        _factory(tracker, 100, hops=5),
        _factory(tracker, 1, hops=1),
        _factory(tracker, 50, hops=3),
    ]
    result = asyncio.run(gather_bounded(factories, limit=3))
    assert result == [100, 1, 50]
