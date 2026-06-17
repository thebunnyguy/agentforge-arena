def bisect_left(sorted_list, target):
    """Return the leftmost index at which ``target`` can be inserted into
    ``sorted_list`` to keep it sorted.

    If ``target`` is already present, this is the index of its first
    occurrence. If absent, it is the index where ``target`` would go.
    """
    lo = 0
    hi = len(sorted_list)
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_list[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo
