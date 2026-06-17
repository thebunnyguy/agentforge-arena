import asyncio


async def gather_bounded(coro_factories, limit):
    """Run coroutine factories with bounded concurrency.

    ``coro_factories`` is a list of zero-argument callables, each of which
    returns a fresh coroutine when called. Run them so that at most ``limit``
    coroutines are in flight at any moment, return their results in the same
    order as ``coro_factories``, and propagate the first exception raised by
    any coroutine.
    """
    if limit <= 0:
        raise ValueError("limit must be a positive integer")

    factories = list(coro_factories)
    results = [None] * len(factories)
    semaphore = asyncio.Semaphore(limit)

    async def _run(index, factory):
        async with semaphore:
            results[index] = await factory()

    if not factories:
        return results

    tasks = [
        asyncio.ensure_future(_run(i, factory))
        for i, factory in enumerate(factories)
    ]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        # Let the cancellations settle so no task is left pending.
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return results
