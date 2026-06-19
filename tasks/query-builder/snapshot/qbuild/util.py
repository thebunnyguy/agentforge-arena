def quote_ident(s):
    """Quote a SQL identifier with double quotes, escaping embedded quotes.

    ``quote_ident('a')`` -> ``'"a"'`` and ``quote_ident('a"b')`` -> ``'"a""b"'``
    (an embedded double quote is doubled, per standard SQL identifier quoting).
    """
    return '"' + s.replace('"', '""') + '"'
