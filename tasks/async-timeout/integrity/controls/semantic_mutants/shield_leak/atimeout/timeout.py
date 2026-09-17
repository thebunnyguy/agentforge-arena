import asyncio


async def with_timeout(make_coro, seconds):
    """Await a coroutine with a timeout.

    SEMANTIC MUTANT: shields the task from cancellation, so on timeout only
    the shield's outer proxy is cancelled -- the real task keeps running.
    """
    task = asyncio.ensure_future(make_coro())
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=seconds)
    except asyncio.TimeoutError:
        raise TimeoutError("operation timed out") from None
