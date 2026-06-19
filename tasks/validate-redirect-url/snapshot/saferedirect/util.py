from urllib.parse import urlparse


def is_https(url):
    """Return ``True`` if ``url`` is an absolute URL using the ``https`` scheme.

    Examples::

        is_https("https://example.com/x") -> True
        is_https("http://example.com/x")  -> False
        is_https("/relative")              -> False
    """
    return urlparse(url).scheme == "https"
