async def run_in_batches(make_coros, batch_size):
    """Run coroutine factories in sequential batches.

    ``make_coros`` is a list of zero-argument callables, each returning a fresh
    coroutine when called. Run them in consecutive batches of at most
    ``batch_size`` factories: the coroutines within one batch run concurrently,
    but a batch must fully complete before the next batch starts. Return all
    results in the same order as ``make_coros``. ``batch_size`` must be a
    positive integer.

    STUB: not implemented yet.
    """
    raise NotImplementedError("run_in_batches is not implemented yet")
