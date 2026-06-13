def dedup(items):
    """Remove duplicate elements from ``items``.

    Returns a list containing each distinct element exactly once, in order of
    first appearance.
    """
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
