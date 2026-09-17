def is_valid_username(name):
    """Valid iff non-empty, alphanumeric only, length <= 20."""
    if not name:
        return False
    if len(name) > 20:
        return False
    for ch in name:
        if not ch.isalnum():
            return False
    return True
