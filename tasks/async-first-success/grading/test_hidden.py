"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These fail against the NotImplementedError stub and pass only with a
correct first-success implementation.

Determinism notes (no timing assertions):
- A "winner" coroutine returns on its first resume (no extra hops), so it
  completes ahead of any coroutine that parks on a never-set ``asyncio.Event``.
- Losers wait on an Event that is never set, so they can only end via
  cancellation; a shared counter/flag records that their CancelledError path
  ran.
- For the all-fail case the factories raise distinct, identifiable errors so the
  test can assert the LAST factory's exception is the one propagated.
"""

import asyncio

import pytest

from afirst import first_success


def _winner(value):
    def make():
        async def run():
            return value  # completes on first resume

        return run()

    return make


def _failer(message):
    def make():
        async def run():
            await asyncio.sleep(0)
            raise ValueError(message)

        return run()

    return make


def _parked_loser(state):
    """A coroutine that never finishes on its own; records cancellation."""

    def make():
        async def run():
            event = asyncio.Event()
            try:
                await event.wait()  # never set
                state["completed"] += 1  # must never happen
                return "unreachable"
            except asyncio.CancelledError:
                state["cancelled"] += 1
                raise

        return run()

    return make


def test_returns_only_success_when_others_fail():
    result = asyncio.run(
        first_success([_failer("a"), _winner("ok"), _failer("b")])
    )
    assert result == "ok"


def test_returns_first_success():
    # The immediate winner resolves before the parked coroutine could ever
    # finish, so its value must be the one returned.
    state = {"completed": 0, "cancelled": 0}
    result = asyncio.run(
        first_success([_parked_loser(state), _winner(123)])
    )
    assert result == 123


def test_all_fail_raises_last_exception():
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(
            first_success([_failer("first"), _failer("middle"), _failer("last")])
        )
    assert str(excinfo.value) == "last"


def test_losers_are_cancelled():
    state = {"completed": 0, "cancelled": 0}

    async def driver():
        result = await first_success(
            [_parked_loser(state), _parked_loser(state), _winner("done")]
        )
        assert result == "done"
        # Let the event loop settle so the losers' cancellation handlers run.
        await asyncio.sleep(0.05)

    asyncio.run(driver())
    assert state["completed"] == 0
    assert state["cancelled"] == 2


def test_single_failure_raises():
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(first_success([_failer("solo")]))
    assert str(excinfo.value) == "solo"


def test_all_fail_propagates_input_order_last_not_temporally_last():
    # The input-order-LAST factory fails FIRST (no hops); earlier factories fail
    # later. The contract raises the LAST factory's exception (input order); an
    # impl that keeps the temporally-last exception would propagate an earlier one.
    def slow_failer(message, hops):
        def make():
            async def run():
                for _ in range(hops):
                    await asyncio.sleep(0)
                raise ValueError(message)
            return run()
        return make

    def fast_failer(message):
        def make():
            async def run():
                raise ValueError(message)
            return run()
        return make

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(
            first_success([slow_failer("early1", 5), slow_failer("early2", 5), fast_failer("inputlast")])
        )
    assert str(excinfo.value) == "inputlast"
