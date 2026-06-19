def count_lines(text):
    """Return the number of lines in ``text``.

    An empty string has zero lines; otherwise the count is the number of
    newline-separated segments (a trailing newline does not add an empty line).

    Examples::

        count_lines("")          -> 0
        count_lines("a")         -> 1
        count_lines("a\\nb")      -> 2
        count_lines("a\\nb\\n")    -> 2
    """
    if text == "":
        return 0
    return len(text.rstrip("\n").split("\n"))
