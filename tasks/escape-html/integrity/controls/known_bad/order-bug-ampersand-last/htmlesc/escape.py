def escape(s):
    """Escape ``s`` for safe inclusion in HTML text/attributes.

    KNOWN-BAD CONTROL: all five characters are escaped, but ampersand is
    escaped LAST instead of first, so the ``&`` introduced by the earlier
    ``&lt;``/``&gt;``/``&quot;``/``&#x27;`` substitutions gets re-escaped into
    ``&amp;lt;`` etc.
    """
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    s = s.replace("'", "&#x27;")
    s = s.replace("&", "&amp;")
    return s
