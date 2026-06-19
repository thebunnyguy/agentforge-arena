def clamp(n, lo, hi):
    """Clamp ``n`` to the inclusive range ``[lo, hi]``.

    Returns ``lo`` if ``n < lo``, ``hi`` if ``n > hi``, otherwise ``n``.
    ``lo`` must not be greater than ``hi``.
    """
    if lo > hi:
        raise ValueError("lo must not be greater than hi")
    if n < lo:
        return lo
    if n > hi:
        return hi
    return n
