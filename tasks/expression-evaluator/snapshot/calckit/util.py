def is_number(s):
    """Return ``True`` if the string ``s`` represents a valid number.

    Accepts an optional leading sign, integer and float literals (e.g. ``"42"``,
    ``"-3"``, ``"1.5"``, ``"+0.25"``). Surrounding whitespace is allowed. Returns
    ``False`` for anything that is not a single numeric literal.
    """
    if not isinstance(s, str):
        return False
    try:
        float(s)
    except (TypeError, ValueError):
        return False
    return True
