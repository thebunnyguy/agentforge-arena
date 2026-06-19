def escape(s):
    """Escape ``s`` for safe inclusion in HTML text/attributes.

    Replaces the five HTML-significant characters with their entities, escaping
    the ampersand FIRST so the entities introduced by the other replacements are
    not double-escaped::

        &  -> &amp;
        <  -> &lt;
        >  -> &gt;
        "  -> &quot;
        '  -> &#x27;
    """
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    s = s.replace("'", "&#x27;")
    return s
