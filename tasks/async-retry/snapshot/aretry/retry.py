async def retry_call(make_coro, attempts):
    """Call ``make_coro`` with retries.

    ``make_coro`` is a zero-argument callable that returns a FRESH coroutine
    each time it is called. Await it up to ``attempts`` times: return the result
    of the first successful await; if every attempt raises, re-raise the LAST
    exception seen. ``attempts`` must be a positive integer.

    STUB: not implemented yet.
    """
    raise NotImplementedError("retry_call is not implemented yet")
