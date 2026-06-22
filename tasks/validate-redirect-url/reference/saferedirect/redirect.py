from urllib.parse import urlparse


def safe_redirect(target, allowed_host):
    """Return ``target`` if it is a safe redirect destination, else raise.

    A redirect is safe when it is either:

    * a relative path that begins with a single ``"/"`` (e.g. ``"/dashboard"``),
      but NOT a protocol-relative ``"//evil.com"``, or
    * an absolute URL whose network location (host) equals ``allowed_host``.

    Anything else — an external absolute URL, a protocol-relative ``"//host"``,
    or a dangerous scheme such as ``"javascript:"`` or ``"data:"`` — raises
    ``ValueError``. Parsing uses ``urllib.parse.urlparse`` and pure string logic
    (no network access).
    """
    if not isinstance(target, str) or not target:
        raise ValueError("redirect target must be a non-empty string")

    # Protocol-relative URLs ("//evil.com/...") are parsed with an empty scheme
    # but a non-empty netloc; reject them explicitly before the relative check.
    if target.startswith("//"):
        raise ValueError("protocol-relative redirect is not allowed: %r" % (target,))

    parsed = urlparse(target)

    # Relative path: no scheme, no host, and an absolute-style leading slash.
    if not parsed.scheme and not parsed.netloc:
        if target.startswith("/"):
            return target
        raise ValueError("redirect target must be an absolute path: %r" % (target,))

    # Only http(s) absolute URLs may be permitted. ANY other scheme is rejected
    # even when it carries a host, e.g. "javascript://host/%0aalert(1)" or
    # "data://host/..." — these parse with a non-empty netloc and would otherwise
    # slip past a host-only check while still being executable/dangerous schemes.
    # urlparse lowercases the scheme, so the comparison is case-insensitive.
    if parsed.scheme not in ("http", "https"):
        raise ValueError("redirect scheme is not allowed: %r" % (target,))

    # An http(s) URL with no host (e.g. "http:/foo") is malformed/dangerous.
    if not parsed.netloc:
        raise ValueError("redirect target must have a host: %r" % (target,))

    # Absolute URL: the host must match the allowed host exactly.
    if parsed.hostname != allowed_host:
        raise ValueError(
            "redirect host %r does not match allowed host %r"
            % (parsed.hostname, allowed_host)
        )

    return target
