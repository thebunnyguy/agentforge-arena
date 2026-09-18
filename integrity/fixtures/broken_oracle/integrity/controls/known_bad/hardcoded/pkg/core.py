def is_valid_username(name):
    """Deliberately wrong (for the integrity engine's known-bad control):
    rejects empty and over-length names correctly, but never checks that
    characters are alphanumeric."""
    if not name:
        return False
    if len(name) > 20:
        return False
    return True
