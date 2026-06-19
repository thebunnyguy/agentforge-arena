import asyncio


async def with_timeout(make_coro, seconds):
    """Await a coroutine with a timeout.

    ``make_coro`` is a zero-argument callable that returns a fresh coroutine.
    Await that coroutine: if it finishes within ``seconds`` seconds, return its
    result. If it does not finish in time, raise ``TimeoutError`` and ensure the
    coroutine is cancelled so no task is left running.
    """
    task = asyncio.ensure_future(make_coro())
    try:
        return await asyncio.wait_for(task, timeout=seconds)
    except asyncio.TimeoutError:
        # asyncio.wait_for already cancels the task and awaits its cancellation
        # on timeout. Re-raise as the builtin TimeoutError (the same object in
        # modern Python) so callers can catch the standard exception.
        raise TimeoutError("operation timed out") from None
