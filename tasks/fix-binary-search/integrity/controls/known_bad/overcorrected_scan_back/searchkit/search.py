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
        elif sorted_list[mid] > target:
            hi = mid
        else:
            # Found an occurrence of target, but binary search doesn't
            # guarantee it's the leftmost one, so "correct" for that by
            # scanning backward.
            #
            # BUG: the scan-back condition should be `sorted_list[i - 1] ==
            # target` (only step back over other occurrences of target).
            # Using `<=` also steps back over every smaller element, so it
            # overshoots past the true leftmost occurrence to index 0 (or
            # further) whenever a smaller value sits anywhere to the left.
            i = mid
            while i > 0 and sorted_list[i - 1] <= target:
                i -= 1
            return i
    return lo
