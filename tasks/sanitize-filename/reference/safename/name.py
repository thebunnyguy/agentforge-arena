def safe_name(name):
    """Return ``name`` if it is a safe single-component filename, else raise.

    A safe filename is a single path component that cannot be used to escape a
    target directory or smuggle a null byte. ``safe_name`` raises ``ValueError``
    when ``name``:

    * is empty,
    * is exactly ``"."`` or ``".."``,
    * contains a path separator (``"/"`` or ``"\\"``),
    * contains a null byte (``"\\x00"``), or
    * contains any ``".."`` path component.

    Otherwise the original ``name`` is returned unchanged. The checks use pure
    string logic only (no real filesystem access).
    """
    if not name:
        raise ValueError("filename must not be empty")
    if "\x00" in name:
        raise ValueError("filename must not contain a null byte")
    if "/" in name or "\\" in name:
        raise ValueError("filename must not contain a path separator: %r" % (name,))
    if name in (".", ".."):
        raise ValueError("filename must not be a relative directory ref: %r" % (name,))
    # Reject any ".." component split on either separator.
    components = name.replace("\\", "/").split("/")
    if ".." in components:
        raise ValueError("filename must not contain a '..' component: %r" % (name,))
    return name
