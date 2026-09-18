"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These fail against the NotImplementedError stub and pass only with a
correct retry implementation.

A mutable counter inside each factory makes the coroutine fail a fixed number of
times before succeeding, so the tests can assert both the success-after-retries
behavior and the exact number of attempts made.
"""

import asyncio

import pytest

from aretry import retry_call


def _factory_fail_then_succeed(fail_times, value, calls):
    """Return a make_coro that fails its first ``fail_times`` calls, then succeeds.

    ``calls`` is a one-element mutable list used to count how many coroutines
    were actually created/awaited.
    """

    def make():
        calls[0] += 1
        attempt = calls[0]

        async def run():
            await asyncio.sleep(0)
            if attempt <= fail_times:
                raise ValueError(f"fail #{attempt}")
            return value

        return run()

    return make


def _factory_always_fail(calls, exc_factory):
    def make():
        calls[0] += 1
        attempt = calls[0]

        async def run():
            await asyncio.sleep(0)
            raise exc_factory(attempt)

        return run()

    return make


def test_succeeds_on_first_try():
    calls = [0]
    result = asyncio.run(
        retry_call(_factory_fail_then_succeed(0, "ok", calls), attempts=3)
    )
    assert result == "ok"
    assert calls[0] == 1


def test_succeeds_on_third_try_after_two_failures():
    calls = [0]
    result = asyncio.run(
        retry_call(_factory_fail_then_succeed(2, "win", calls), attempts=3)
    )
    assert result == "win"
    assert calls[0] == 3


def test_all_attempts_fail_reraises_last():
    calls = [0]

    def exc_factory(attempt):
        return ValueError(f"boom-{attempt}")

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(retry_call(_factory_always_fail(calls, exc_factory), attempts=3))
    # The LAST exception (from the 3rd attempt) must be the one re-raised.
    assert str(excinfo.value) == "boom-3"
    assert calls[0] == 3


def test_attempts_one_that_fails_raises():
    calls = [0]

    def exc_factory(attempt):
        return RuntimeError(f"only-{attempt}")

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(retry_call(_factory_always_fail(calls, exc_factory), attempts=1))
    assert str(excinfo.value) == "only-1"
    assert calls[0] == 1


def test_does_not_retry_after_success():
    # Once a call succeeds, no further coroutines should be created.
    calls = [0]
    result = asyncio.run(
        retry_call(_factory_fail_then_succeed(1, 7, calls), attempts=5)
    )
    assert result == 7
    assert calls[0] == 2


def test_zero_attempts_raises_value_error():
    # attempts must be a positive integer; attempts=0 must raise ValueError, not a
    # TypeError from re-raising a None "last exception".
    async def make():
        return "unused"

    with pytest.raises(ValueError):
        asyncio.run(retry_call(make, 0))


def test_cancelled_error_propagates_without_retry():
    """SEMANTIC PROPERTY (task.json contract): only ``Exception`` subclasses
    count as a failed attempt. A ``BaseException`` that is not an ``Exception``
    (``asyncio.CancelledError`` here) must propagate immediately out of the
    attempt that raised it - it must NOT be caught, stored, and retried like an
    ordinary failure.

    The discriminating assertion is ``calls[0] == 1``, not merely that a
    CancelledError eventually comes out of ``asyncio.run``: an implementation
    that widens ``except Exception`` to ``except BaseException`` still ends up
    re-raising a CancelledError after exhausting every attempt (the same
    exception object survives as ``last_exc``), so a test that only checked
    the exception type would pass that implementation. What must actually
    happen is that make_coro() is never called again after the first
    CancelledError - i.e. the exception left the function on the very first
    attempt instead of being swallowed and retried.
    """
    calls = [0]

    def exc_factory(attempt):
        return asyncio.CancelledError(f"cancel-{attempt}")

    async def go():
        return await retry_call(_factory_always_fail(calls, exc_factory), attempts=3)

    with pytest.raises(asyncio.CancelledError) as excinfo:
        asyncio.run(go())
    assert str(excinfo.value) == "cancel-1"
    assert calls[0] == 1
