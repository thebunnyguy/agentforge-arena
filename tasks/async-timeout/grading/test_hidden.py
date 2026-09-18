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
    # SEMANTIC CONTRACT: by the moment with_timeout raises TimeoutError, the
    # task/coroutine it spawned for the timed-out operation must already be
    # fully finished (cancelled) -- not merely destined to be swept up later.
    #
    # This must be checked from *inside* the still-running event loop, right
    # after with_timeout raises, and BEFORE asyncio.run() returns:
    # asyncio.run()'s own shutdown sweep (_cancel_all_tasks) unconditionally
    # cancels every task still pending when the loop closes, so a check
    # performed only after asyncio.run() returns cannot distinguish
    # "with_timeout itself cancelled the leaked task" from "with_timeout left
    # the task running and asyncio.run's shutdown sweep cleaned it up
    # afterwards" -- both make a cleanup flag observed post-hoc look
    # identical. That is the exact gap a "never call .cancel()" bug and a
    # "shield the inner task from cancellation" bug both slip through.
    #
    # We close that gap two ways, both evaluated while the loop is still
    # running:
    #
    #   1. We grab a strong, externally-held handle on the task actually
    #      running the timed-out coroutine (via asyncio.current_task() as the
    #      very first thing that coroutine does) and assert it is done. We
    #      hold this handle ourselves because, once with_timeout's own local
    #      variable referencing that task goes out of scope, the only
    #      remaining reference is a cycle (task -> its running coroutine
    #      frame -> the Event it awaits -> the Event's waiter callbacks ->
    #      back to the task); whether asyncio.all_tasks() alone still reports
    #      it would then depend on whether the cyclic garbage collector
    #      happened to run yet, which is not deterministic. Holding our own
    #      reference sidesteps that and makes the check exact. (An
    #      implementation that never wraps the coroutine in a separate task
    #      at all -- e.g. driving it inline under `async with
    #      asyncio.timeout(...)` -- has nothing to leak, so we also accept
    #      the case where that "task" is simply the current task itself.)
    #   2. As a second, implementation-agnostic view of the same property: no
    #      task besides the current one may remain in asyncio.all_tasks().
    #
    # A correct implementation (which must fully cancel -- and await the
    # cancellation of -- the task before raising TimeoutError) satisfies
    # both. An implementation that forgets to call .cancel() on timeout, or
    # that shields the inner task from cancellation (e.g. via
    # asyncio.shield()), satisfies neither: the real inner task is still
    # pending in the loop when TimeoutError is raised.
    state = {"completed": False, "cleanup_ran": False, "task": None}

    def make():
        async def run():
            state["task"] = asyncio.current_task()
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
        before = asyncio.all_tasks() - {asyncio.current_task()}
        with pytest.raises(TimeoutError):
            await with_timeout(make, seconds=0.05)

        inner_task = state["task"]
        assert inner_task is not None
        assert inner_task is asyncio.current_task() or inner_task.done(), (
            "with_timeout raised TimeoutError but the task running the "
            "timed-out coroutine is still pending"
        )

        after = asyncio.all_tasks() - {asyncio.current_task()}
        leaked = after - before
        assert not leaked, (
            "with_timeout raised TimeoutError but left task(s) still "
            f"running in the event loop: {leaked!r}"
        )

        # Checked here, still inside the running loop, so a task that was
        # genuinely cancelled by with_timeout (rather than merely swept up
        # by asyncio.run's shutdown handler afterwards) has definitely
        # already run its cleanup path.
        assert state["completed"] is False
        assert state["cleanup_ran"] is True

    asyncio.run(driver())


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
