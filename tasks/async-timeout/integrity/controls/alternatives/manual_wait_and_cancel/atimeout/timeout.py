import asyncio


async def with_timeout(make_coro, seconds):
    """Await a coroutine with a timeout.

    ALTERNATIVE: drives asyncio.wait() directly instead of asyncio.wait_for,
    and explicitly blocks on the cancelled task's completion before raising,
    rather than relying on wait_for's internal cancel-and-await sequence.
    """
    task = asyncio.ensure_future(make_coro())
    done, pending = await asyncio.wait({task}, timeout=seconds)
    if pending:
        for pending_task in pending:
            pending_task.cancel()
        await asyncio.wait(pending)
        raise TimeoutError("operation timed out")
    return task.result()
