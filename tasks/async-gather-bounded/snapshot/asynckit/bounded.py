async def gather_bounded(coro_factories, limit):
    """Run coroutine factories with bounded concurrency.

    ``coro_factories`` is a list of zero-argument callables, each of which
    returns a fresh coroutine when called. Run them so that at most ``limit``
    coroutines are in flight at any moment, return their results in the same
    order as ``coro_factories``, and propagate the first exception raised by
    any coroutine.

    STUB: not implemented yet.
    """
    raise NotImplementedError("gather_bounded is not implemented yet")
