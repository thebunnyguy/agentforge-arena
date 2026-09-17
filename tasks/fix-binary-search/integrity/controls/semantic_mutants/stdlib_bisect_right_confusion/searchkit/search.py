import bisect


def bisect_left(sorted_list, target):
    """Return the leftmost index at which ``target`` can be inserted into
    ``sorted_list`` to keep it sorted.

    If ``target`` is already present, this is the index of its first
    occurrence. If absent, it is the index where ``target`` would go.

    BUG: delegates to ``bisect.bisect``, which the stdlib documents as an
    alias for ``bisect.bisect_right`` -- not ``bisect.bisect_left``. This
    resolves duplicates to the rightmost occurrence instead of the leftmost.
    """
    return bisect.bisect(sorted_list, target)
