def is_positive_int(n):
    """Return True iff ``n`` is an integer strictly greater than zero.

    Booleans are not accepted as integers here. A small, already-correct helper
    used elsewhere in the package.
    """
    if isinstance(n, bool):
        return False
    return isinstance(n, int) and n > 0
