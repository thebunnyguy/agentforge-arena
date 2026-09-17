import asyncio


async def with_timeout(make_coro, seconds):
    """Await a coroutine with a timeout.

    KNOWN-BAD: single-defect variant of the correct wait()-based approach --
    identical control flow, but the `if pending:` branch never calls
    `.cancel()` before raising, so the task is left running (leaked).
    """
    task = asyncio.ensure_future(make_coro())
    done, pending = await asyncio.wait({task}, timeout=seconds)
    if pending:
        raise TimeoutError("operation timed out")
    return task.result()
