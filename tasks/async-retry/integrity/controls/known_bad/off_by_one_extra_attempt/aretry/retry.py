async def retry_call(make_coro, attempts):
    """KNOWN-BAD (for the integrity engine): off-by-one on the retry count.

    Loops ``attempts + 1`` times instead of ``attempts`` times, so every
    all-fail scenario makes one extra call to ``make_coro()`` and re-raises
    the exception from that extra, unrequested attempt rather than the last
    exception from the ``attempts``'th call.
    """
    if attempts <= 0:
        raise ValueError("attempts must be a positive integer")

    last_exc = None
    for _ in range(attempts + 1):
        try:
            return await make_coro()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, per spec
            last_exc = exc
    raise last_exc
