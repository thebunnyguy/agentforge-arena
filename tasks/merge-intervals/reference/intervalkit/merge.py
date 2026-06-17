def merge(intervals):
    """Merge overlapping and touching intervals.

    Given a list of ``(start, end)`` integer intervals (possibly unsorted),
    return a sorted list of merged, non-overlapping intervals. Two intervals
    that merely touch — e.g. ``(1, 2)`` and ``(2, 3)`` — merge into a single
    interval ``(1, 3)``.
    """
    ordered = sorted(intervals)
    out = []
    for start, end in ordered:
        if out and start <= out[-1][1]:
            prev_start, prev_end = out[-1]
            out[-1] = (prev_start, max(prev_end, end))
        else:
            out.append((start, end))
    return out
