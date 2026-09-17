def escape(s):
    """Escape ``s`` for safe inclusion in HTML text/attributes.

    SEMANTIC MUTANT (security-relevant near-miss): correctly fixes the
    described bug -- & is now escaped, and it is escaped FIRST so '<&>'
    round-trips correctly -- but the fix stops at & < > and never adds quote
    escaping. Safe for HTML text content, but a value dropped into a quoted
    attribute (e.g. value="...") can still break out of the attribute using
    an unescaped '"' or "'" and inject arbitrary attributes/event handlers.
    """
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    return s
