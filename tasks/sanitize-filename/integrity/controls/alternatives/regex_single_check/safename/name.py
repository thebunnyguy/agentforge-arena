import re

# Any of: '/', '\', or a null byte.
_UNSAFE_CHARS = re.compile(r"[/\\\x00]")
_RELATIVE_REFS = {".", ".."}


def safe_name(name):
    """Alternative correct implementation: a single regex scan for unsafe
    characters plus a set-membership check for '.'/'..', rather than the
    reference's sequence of separate if-checks and a split-into-components
    loop. Behaviorally equivalent: any '/' or '\\' is rejected outright by
    the regex, so the only way a '..' path *component* can occur is when the
    whole name equals '..', which the set check already covers."""
    if not name or name in _RELATIVE_REFS or _UNSAFE_CHARS.search(name):
        raise ValueError("unsafe filename: %r" % (name,))
    return name
