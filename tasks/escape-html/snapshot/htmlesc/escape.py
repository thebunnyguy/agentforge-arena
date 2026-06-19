def escape(s):
    """Escape ``s`` for safe inclusion in HTML text/attributes.

    The five HTML-significant characters must be replaced by their entities::

        &  -> &amp;
        <  -> &lt;
        >  -> &gt;
        "  -> &quot;
        '  -> &#x27;

    The ampersand must be escaped FIRST, so that the ampersands introduced by the
    other replacements (``&lt;`` etc.) are not themselves re-escaped into
    ``&amp;lt;``.

    BUG: this implementation escapes ``<`` and ``>`` but forgets ``&`` (and the
    quotes), so a literal ``&`` is left unescaped and an input like ``"<&>"`` is
    rendered incorrectly.
    """
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    return s
