async def retry_call(make_coro, attempts):
    """KNOWN-BAD (for the integrity engine): calls ``make_coro()`` only ONCE,
    before the loop, and re-awaits that single coroutine object on every
    retry instead of calling ``make_coro()`` again each attempt.

    This misreads the "zero-argument callable that returns a FRESH coroutine
    each time it is called" contract: after the first await completes (by
    returning or raising), awaiting the same coroutine object again raises
    RuntimeError('cannot reuse already awaited coroutine'), so any scenario
    needing more than one attempt breaks instead of actually retrying.
    """
    if attempts <= 0:
        raise ValueError("attempts must be a positive integer")

    coro = make_coro()
    last_exc = None
    for _ in range(attempts):
        try:
            return await coro
        except Exception as exc:  # noqa: BLE001 - deliberately broad, per spec
            last_exc = exc
    raise last_exc
