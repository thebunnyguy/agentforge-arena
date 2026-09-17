_ENTITIES = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#x27;",
}


def escape(s):
    """Escape ``s`` for safe inclusion in HTML text/attributes.

    ALTERNATIVE (structurally different, behaviorally equivalent) solution:
    rather than chaining ``str.replace`` calls over the whole (partially
    already-rewritten) string -- which is why the reference must special-case
    ampersand-first -- this scans the ORIGINAL string exactly once,
    character by character, and looks each character up in a mapping table.
    Because each input character is only ever inspected once, there is no
    way for an entity produced for one character to be re-scanned and
    re-escaped, so no explicit ordering rule is needed at all.
    """
    return "".join(_ENTITIES.get(ch, ch) for ch in s)
