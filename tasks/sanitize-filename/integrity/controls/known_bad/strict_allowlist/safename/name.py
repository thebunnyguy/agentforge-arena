import re

_ALLOWED = re.compile(r"[A-Za-z0-9._-]+")


def safe_name(name):
    """Buggy control: correctly implements every check the spec requires, but
    additionally rejects any name containing a character outside a strict
    allowlist. The spec only requires rejecting empty/'.'/'..'/separators/null
    byte/'..' components; names with a space, non-ASCII characters, or other
    ordinary punctuation must still be returned unchanged, which this does
    not do."""
    if not name:
        raise ValueError("filename must not be empty")
    if "\x00" in name:
        raise ValueError("filename must not contain a null byte")
    if "/" in name or "\\" in name:
        raise ValueError("filename must not contain a path separator: %r" % (name,))
    if name in (".", ".."):
        raise ValueError("filename must not be a relative directory ref: %r" % (name,))
    components = name.replace("\\", "/").split("/")
    if ".." in components:
        raise ValueError("filename must not contain a '..' component: %r" % (name,))
    # BUG: extra restriction not part of the spec, over-rejects valid names.
    if not _ALLOWED.fullmatch(name):
        raise ValueError("filename contains disallowed characters: %r" % (name,))
    return name
