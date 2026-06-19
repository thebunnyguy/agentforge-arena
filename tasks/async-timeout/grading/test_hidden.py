"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These fail against the NotImplementedError stub and pass only with a
correct timeout-and-cancel implementation.

Timing uses GENEROUS, non-flaky margins: the "never finishes" coroutine awaits
an ``asyncio.Event`` that is never set, so it can only end via cancellation. The
timeout is small (0.05s) but the work is infinite, so the gap is unbounded.
"""

import asyncio

import pytest

from atimeout import with_timeout


def _instant_factory(value):
    def make():
        async def run():
            return value

        return run()

    return make


def test_instant_coro_returns_its_value():
    result = asyncio.run(with_timeout(_instant_factory("hello"), seconds=1.0))
    assert result == "hello"


def test_never_finishing_coro_raises_timeout_error():
    def make():
        async def run():
            event = asyncio.Event()
            await event.wait()  # never set -> only ends via cancellation
            return "unreachable"

        return run()

    with pytest.raises(TimeoutError):
        asyncio.run(with_timeout(make, seconds=0.05))


def test_coroutine_is_cancelled_on_timeout():
    # A flag confirms the coroutine did NOT run to completion and that its
    # cancellation/cleanup path executed when the timeout fired.
    state = {"completed": False, "cleanup_ran": False}

    def make():
        async def run():
            event = asyncio.Event()
            try:
                await event.wait()  # never set
                state["completed"] = True  # must never happen
                return "done"
            except asyncio.CancelledError:
                state["cleanup_ran"] = True
                raise

        return run()

    async def driver():
        with pytest.raises(TimeoutError):
            await with_timeout(make, seconds=0.05)
        # Give the event loop a moment to let the cancellation settle so the
        # cleanup handler is guaranteed to have run.
        await asyncio.sleep(0.05)

    asyncio.run(driver())
    assert state["completed"] is False
    assert state["cleanup_ran"] is True


def test_value_returned_before_timeout_with_small_work():
    # A coroutine that does a couple of cooperative hops still finishes well
    # within a comfortable timeout and returns its value.
    def make():
        async def run():
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return 99

        return run()

    result = asyncio.run(with_timeout(make, seconds=1.0))
    assert result == 99
