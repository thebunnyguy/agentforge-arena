def safe_name(name):
    """Buggy control: rejects any occurrence of the substring ".." instead of
    checking for a whole ".." path component. Over-rejects legitimate names
    like "safe..file" that merely contain two consecutive dots."""
    if not name:
        raise ValueError("filename must not be empty")
    if "\x00" in name:
        raise ValueError("filename must not contain a null byte")
    if "/" in name or "\\" in name:
        raise ValueError("filename must not contain a path separator: %r" % (name,))
    if name in (".", ".."):
        raise ValueError("filename must not be a relative directory ref: %r" % (name,))
    # BUG: substring check instead of a whole-component check.
    if ".." in name:
        raise ValueError("filename must not contain '..': %r" % (name,))
    return name
