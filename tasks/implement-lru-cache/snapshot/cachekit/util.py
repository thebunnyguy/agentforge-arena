def clamp(x, lo, hi):
    """Clamp ``x`` into the inclusive range ``[lo, hi]``.

    Returns ``lo`` if ``x < lo``, ``hi`` if ``x > hi``, otherwise ``x``.
    """
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x
