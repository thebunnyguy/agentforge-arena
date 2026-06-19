def safe_name(name):
    """Return ``name`` if it is a safe single-component filename.

    A safe filename is a single path component that cannot be used to escape a
    target directory or smuggle a null byte. ``safe_name`` must raise
    ``ValueError`` when ``name``:

    * is empty,
    * is exactly ``"."`` or ``".."``,
    * contains a path separator (``"/"`` or ``"\\"``),
    * contains a null byte (``"\\x00"``), or
    * contains any ``".."`` path component.

    Otherwise the original ``name`` is returned unchanged.

    BUG: this implementation performs no validation and simply returns ``name``
    unchanged, so ``"../etc/passwd"`` and other unsafe names slip through.
    """
    return name
