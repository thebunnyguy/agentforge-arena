import asyncio


async def with_timeout(make_coro, seconds):
    """Await a coroutine with a timeout.

    KNOWN-BAD: cancels the task properly (cleanup code inside the coroutine
    does run) but swallows the resulting CancelledError and returns None
    instead of raising TimeoutError to the caller.
    """
    task = asyncio.ensure_future(make_coro())
    done, pending = await asyncio.wait({task}, timeout=seconds)
    if task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass  # BUG: swallowed instead of signalling the timeout
        return None
    return task.result()
