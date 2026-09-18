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
- For external-cancellation, a shared "started" counter is polled with bounded
  ``await asyncio.sleep(0)`` hops (never a wall-clock sleep) until every child
  has actually begun running, so the outer call is provably parked at its own
  await point before it is cancelled.
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


def test_empty_make_coros_raises_value_error():
    # Semantic contract (task.json description, clarified in v1.0.2): make_coros
    # must be non-empty; calling with zero factories must raise ValueError. This
    # is a documented input-validation requirement, not an implementation detail
    # -- a correct implementation must reject empty input explicitly rather than
    # merely happening to blow up with some unrelated, un-promised exception
    # while trying to run zero coroutines (e.g. an internal IndexError from
    # indexing into a container that ended up empty because the guard was never
    # there in the first place).
    with pytest.raises(ValueError):
        asyncio.run(first_success([]))


def test_external_cancellation_cancels_children_and_propagates():
    # Semantic contract: first_success "cancels the remaining coroutines" (task
    # description) -- and this must hold not only when a winner is found, but
    # also when the first_success() call itself is cancelled from the outside
    # before any factory has resolved. A correct implementation must (a)
    # propagate the cancellation as asyncio.CancelledError rather than
    # swallowing it and surfacing something else, and (b) actually cancel every
    # still-running factory coroutine itself -- not merely abandon them for the
    # event loop's own shutdown machinery to clean up later (which would hide a
    # real task leak in production use, where nothing ever calls asyncio.run()
    # again to sweep up orphans).
    state = {"started": 0, "completed": 0, "cancelled": 0}

    def _parked_loser():
        def make():
            async def run():
                state["started"] += 1
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

    async def driver():
        outer = asyncio.ensure_future(
            first_success([_parked_loser(), _parked_loser(), _parked_loser()])
        )
        # Deterministically wait (no timing assumption -- a state check, not a
        # sleep) until all three children have actually started and parked on
        # their Event, so `outer` is guaranteed to already be suspended inside
        # its own wait-loop -- not still in its synchronous setup code -- when
        # we cancel it below. Bounded so a broken implementation that never
        # gets all three children running fails fast instead of hanging.
        for _ in range(10_000):
            if state["started"] >= 3:
                break
            await asyncio.sleep(0)
        else:
            pytest.fail(
                "children never started running concurrently; cannot exercise "
                "external cancellation"
            )
        outer.cancel()
        # Bounded wait (a safety net against a hang, not a correctness-via-
        # timing check): a correct implementation reacts to cancellation on
        # its very next suspension point, so 5s is enormous headroom.
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(outer, timeout=5)
        # The cancellation must not have been swallowed/replaced, and every
        # child must have been cancelled by first_success itself.
        assert state["cancelled"] == 3
        assert state["completed"] == 0
        leaked = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        assert leaked == []

    asyncio.run(driver())


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
