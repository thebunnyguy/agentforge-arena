async def first_success(make_coros):
    """Return the result of the first coroutine to succeed.

    ``make_coros`` is a list of zero-argument callables, each returning a fresh
    coroutine when called. Run them all concurrently. Return the result of the
    first coroutine that completes successfully and cancel the rest. If every
    coroutine fails, raise the last exception (the exception raised by the last
    factory in input order). ``make_coros`` must be non-empty.

    STUB: not implemented yet.
    """
    raise NotImplementedError("first_success is not implemented yet")
