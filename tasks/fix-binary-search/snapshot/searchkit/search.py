def bisect_left(sorted_list, target):
    """Return the leftmost index at which ``target`` can be inserted into
    ``sorted_list`` to keep it sorted.

    If ``target`` is already present, this is the index of its first
    occurrence. If absent, it is the index where ``target`` would go.

    BUG: the lower bound is advanced past equal elements, so when the target
    is present (especially among duplicates) the returned index is too far to
    the right, and some insertion points for absent targets are also wrong.
    """
    lo = 0
    hi = len(sorted_list)
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_list[mid] < target:
            lo = mid + 1
        elif sorted_list[mid] == target:
            lo = mid + 1
        else:
            hi = mid
    return lo
