def escape(s):
    """Escape ``s`` for safe inclusion in HTML text/attributes.

    KNOWN-BAD CONTROL: ampersand-first ordering is correct, and the double
    quote is escaped, but the single quote is left untouched.
    """
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    return s
