def safe_name(name):
    """Buggy control: "sanitizes" unsafe input into a safe basename instead of
    raising ValueError. A plausible misreading of "sanitize-filename" as an
    instruction to clean the name rather than reject unsafe input outright."""
    if not name:
        raise ValueError("filename must not be empty")
    cleaned = name.replace("\x00", "")
    cleaned = cleaned.replace("\\", "/")
    base = cleaned.split("/")[-1]
    if base in ("", ".", ".."):
        raise ValueError("filename must not be a relative directory ref: %r" % (name,))
    return base
