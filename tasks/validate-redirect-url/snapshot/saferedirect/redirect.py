from urllib.parse import urlparse  # noqa: F401  (intended for the fix)


def safe_redirect(target, allowed_host):
    """Return ``target`` if it is a safe redirect destination.

    A redirect is safe when it is either:

    * a relative path that begins with a single ``"/"`` (e.g. ``"/dashboard"``),
      but NOT a protocol-relative ``"//evil.com"``, or
    * an absolute URL whose network location (host) equals ``allowed_host``.

    Anything else — an external absolute URL, a protocol-relative ``"//host"``,
    or a dangerous scheme such as ``"javascript:"`` or ``"data:"`` — must raise
    ``ValueError``.

    BUG: this implementation trusts the caller and returns ``target`` unchanged,
    which is a classic open-redirect vulnerability.
    """
    return target
