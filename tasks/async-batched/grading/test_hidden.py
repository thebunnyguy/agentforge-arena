"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These fail against the NotImplementedError stub and pass only with a
correct sequential-batches implementation.

Concurrency is checked WITHOUT timing: each coroutine increments a shared
counter on entry, yields control via ``asyncio.sleep(0)`` so siblings in the
same batch get scheduled, records the peak observed in-flight count, then
decrements. A correct batched scheduler never lets the peak exceed
``batch_size``; a serial (batch_size=1) scheduler keeps the peak at 1.
"""

import asyncio

from abatch import run_in_batches


class Tracker:
    def __init__(self):
        self.current = 0
        self.peak = 0


def _factory(tracker, value, hops=3):
    def make():
        async def run():
            tracker.current += 1
            tracker.peak = max(tracker.peak, tracker.current)
            # Yield control several times so that, if the scheduler allowed it,
            # more than `batch_size` coroutines would overlap and bump the peak.
            for _ in range(hops):
                await asyncio.sleep(0)
            tracker.current -= 1
            return value

        return run()

    return make


def test_results_in_input_order():
    tracker = Tracker()
    factories = [_factory(tracker, v) for v in [10, 20, 30, 40, 50]]
    result = asyncio.run(run_in_batches(factories, batch_size=2))
    assert result == [10, 20, 30, 40, 50]


def test_peak_concurrency_never_exceeds_batch_size():
    tracker = Tracker()
    factories = [_factory(tracker, v) for v in range(12)]
    result = asyncio.run(run_in_batches(factories, batch_size=3))
    assert result == list(range(12))
    assert tracker.peak <= 3
    assert tracker.peak >= 1


def test_batch_size_one_is_fully_serial():
    tracker = Tracker()
    factories = [_factory(tracker, v) for v in range(6)]
    result = asyncio.run(run_in_batches(factories, batch_size=1))
    assert result == list(range(6))
    assert tracker.peak == 1


def test_empty_list_returns_empty():
    assert asyncio.run(run_in_batches([], batch_size=4)) == []


def test_batch_size_greater_than_or_equal_to_length():
    tracker = Tracker()
    factories = [_factory(tracker, v) for v in [7, 8, 9]]
    result = asyncio.run(run_in_batches(factories, batch_size=3))
    assert result == [7, 8, 9]
    assert tracker.peak <= 3

    tracker2 = Tracker()
    factories2 = [_factory(tracker2, v) for v in [7, 8, 9]]
    result2 = asyncio.run(run_in_batches(factories2, batch_size=10))
    assert result2 == [7, 8, 9]
    assert tracker2.peak <= 3
