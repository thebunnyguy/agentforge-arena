def is_valid_username(name):
    """Spec: valid iff non-empty, alphanumeric only, length <= 20.

    BUG: the for-loop never executes on an empty string, so an empty name
    falls through to `return True` instead of being rejected.
    """
    if len(name) > 20:
        return False
    for ch in name:
        if not ch.isalnum():
            return False
    return True
