async def retry_call(make_coro, attempts):
    """Call ``make_coro`` with retries.

    ``make_coro`` is a zero-argument callable that returns a FRESH coroutine
    each time it is called. Await it up to ``attempts`` times: return the result
    of the first successful await; if every attempt raises, re-raise the LAST
    exception seen. ``attempts`` must be a positive integer.
    """
    if attempts <= 0:
        raise ValueError("attempts must be a positive integer")

    last_exc = None
    for _ in range(attempts):
        try:
            return await make_coro()
        except Exception as exc:  # noqa: BLE001 - we deliberately retry on any error
            last_exc = exc
    raise last_exc
