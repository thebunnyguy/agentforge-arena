import asyncio


async def with_timeout(make_coro, seconds):
    """Await a coroutine with a timeout.

    KNOWN-BAD: cancels the task and awaits it (cleanup does run), but does
    not catch the CancelledError that awaiting a cancelled task raises, so
    it propagates to the caller instead of being converted to TimeoutError.
    """
    task = asyncio.ensure_future(make_coro())
    done, pending = await asyncio.wait({task}, timeout=seconds)
    if pending:
        task.cancel()
        await task  # BUG: raises CancelledError here, uncaught
    return task.result()
