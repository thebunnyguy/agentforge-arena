def has_extension(name, ext):
    """Return ``True`` if ``name`` ends with the extension ``ext``.

    The comparison is case-insensitive and a leading dot on ``ext`` is optional,
    so ``has_extension("Report.TXT", "txt")`` and
    ``has_extension("report.txt", ".txt")`` are both ``True``.
    """
    ext = ext.lower().lstrip(".")
    name = name.lower()
    return name.endswith("." + ext)
