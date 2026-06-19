import asyncio


async def run_in_batches(make_coros, batch_size):
    """Run coroutine factories in sequential batches.

    ``make_coros`` is a list of zero-argument callables, each returning a fresh
    coroutine when called. Run them in consecutive batches of at most
    ``batch_size`` factories: the coroutines within one batch run concurrently,
    but a batch must fully complete before the next batch starts. Return all
    results in the same order as ``make_coros``. ``batch_size`` must be a
    positive integer.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")

    factories = list(make_coros)
    results = []
    for start in range(0, len(factories), batch_size):
        batch = factories[start:start + batch_size]
        # Run this batch concurrently; gather preserves input order. The next
        # batch is only started after this await returns.
        batch_results = await asyncio.gather(*(make() for make in batch))
        results.extend(batch_results)
    return results
