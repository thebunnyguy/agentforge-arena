async def retry_call(make_coro, attempts):
    """KNOWN-BAD (for the integrity engine): forgets to validate ``attempts``.

    Implements the happy-path retry loop correctly but never checks that
    ``attempts`` is a positive integer. With ``attempts=0`` the loop body
    never executes, ``last_exc`` is never assigned, and ``raise last_exc``
    raises ``TypeError: exceptions must derive from BaseException`` instead
    of the documented ``ValueError``.
    """
    last_exc = None
    for _ in range(attempts):
        try:
            return await make_coro()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, per spec
            last_exc = exc
    raise last_exc
