def clamp(n, lo, hi):
    """Clamp ``n`` into the inclusive range ``[lo, hi]``.

    Returns ``lo`` if ``n < lo``, ``hi`` if ``n > hi``, otherwise ``n``.
    """
    if n < lo:
        return lo
    if n > hi:
        return hi
    return n
