def flatten(nested):
    """Flatten one level of nesting: ``[[1, 2], [3]] -> [1, 2, 3]``."""
    out = []
    for sub in nested:
        out.extend(sub)
    return out
