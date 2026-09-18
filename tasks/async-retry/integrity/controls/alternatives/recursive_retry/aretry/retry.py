async def retry_call(make_coro, attempts):
    """ALTERNATIVE (for the integrity engine): recursive implementation.

    Structurally different from the reference's for-loop + last_exc
    accumulator: this version recurses with an explicit "remaining attempts"
    counter and re-raises via a bare ``raise`` from inside the except block
    of the final frame, rather than storing the exception in a variable and
    raising it after the loop. Behaviorally equivalent: returns the result
    of the first successful call, re-raises the LAST exception if every
    attempt fails, makes no further calls after a success, and validates
    ``attempts`` up front.
    """
    if attempts <= 0:
        raise ValueError("attempts must be a positive integer")

    async def _attempt(remaining):
        try:
            return await make_coro()
        except Exception:  # noqa: BLE001 - we deliberately retry on any error
            if remaining <= 1:
                raise
            return await _attempt(remaining - 1)

    return await _attempt(attempts)
