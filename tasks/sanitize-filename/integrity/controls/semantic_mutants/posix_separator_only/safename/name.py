import os


def safe_name(name):
    """Security-relevant semantic mutant: detects path separators via
    os.sep/os.altsep instead of the literal characters '/' and '\\'. On a
    POSIX host os.altsep is None, so backslash-based traversal payloads slip
    through unrejected even though the task explicitly requires rejecting
    both '/' and '\\'."""
    if not name:
        raise ValueError("filename must not be empty")
    if "\x00" in name:
        raise ValueError("filename must not contain a null byte")
    if os.sep in name or (os.altsep and os.altsep in name):
        raise ValueError("filename must not contain a path separator: %r" % (name,))
    if name in (".", ".."):
        raise ValueError("filename must not be a relative directory ref: %r" % (name,))
    components = name.split(os.sep)
    if ".." in components:
        raise ValueError("filename must not contain a '..' component: %r" % (name,))
    return name
