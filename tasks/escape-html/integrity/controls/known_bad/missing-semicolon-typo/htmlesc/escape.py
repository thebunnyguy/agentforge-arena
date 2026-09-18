def escape(s):
    """Escape ``s`` for safe inclusion in HTML text/attributes.

    KNOWN-BAD CONTROL: ampersand-first ordering is correct and all five
    characters are handled, but the double-quote entity is missing its
    trailing semicolon ('&quot' instead of '&quot;') -- a plausible typo.
    """
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot")
    s = s.replace("'", "&#x27;")
    return s
