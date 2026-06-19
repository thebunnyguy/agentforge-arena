def is_blank(s):
    """Return ``True`` if ``s`` is empty or contains only whitespace.

    Examples::

        is_blank("")        -> True
        is_blank("   ")     -> True
        is_blank("\\t\\n")    -> True
        is_blank(" x ")     -> False
    """
    return s.strip() == ""
