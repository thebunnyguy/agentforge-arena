import posixpath


def normalize(p):
    """Normalize a POSIX path string by collapsing redundant separators and
    up-level references using pure string logic (``posixpath.normpath``).

    Examples::

        normalize("a/./b/../c")  -> "a/c"
        normalize("a//b/")       -> "a/b"
    """
    return posixpath.normpath(p)
