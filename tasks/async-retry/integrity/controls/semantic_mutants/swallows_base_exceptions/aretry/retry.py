async def retry_call(make_coro, attempts):
    """SEMANTIC MUTANT (for the integrity engine): catches ``BaseException``
    instead of ``Exception``.

    This swallows and retries on ``asyncio.CancelledError`` and other
    non-``Exception`` signals (``BaseException`` subclasses) instead of
    letting them propagate immediately, breaking cooperative cancellation.
    A realistic near-miss: broadening the except clause "to be extra safe"
    is exactly the kind of partial fix a coding agent might apply while
    still passing every test that only raises ordinary ``Exception``
    subclasses.
    """
    if attempts <= 0:
        raise ValueError("attempts must be a positive integer")

    last_exc = None
    for _ in range(attempts):
        try:
            return await make_coro()
        except BaseException as exc:  # noqa: BLE001 - deliberate mutant
            last_exc = exc
    raise last_exc
