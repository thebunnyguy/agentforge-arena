def contains(interval, point):
    """Return True if ``point`` lies within ``interval`` (inclusive).

    ``interval`` is a ``(start, end)`` pair with ``start <= end``.
    """
    start, end = interval
    return start <= point <= end
