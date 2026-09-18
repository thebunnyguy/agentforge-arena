from urllib.parse import urlparse

_DANGEROUS_SCHEMES = ("javascript", "data")


def safe_redirect(target, allowed_host):
    """Return ``target`` if it is a safe redirect destination, else raise.

    BUG (known_bad control): validates the scheme with a blacklist of
    "known dangerous" schemes instead of an allow-list of "known safe"
    ones. Any scheme not on the blacklist -- e.g. "ftp:", "file:",
    "gopher:" -- slips straight through to the host check, so
    "ftp://app.example.com/file" is wrongly accepted even though it is
    not a valid web redirect target.
    """
    if not isinstance(target, str) or not target:
        raise ValueError("redirect target must be a non-empty string")

    if target.startswith("//"):
        raise ValueError("protocol-relative redirect is not allowed: %r" % (target,))

    parsed = urlparse(target)

    if not parsed.scheme and not parsed.netloc:
        if target.startswith("/"):
            return target
        raise ValueError("redirect target must be an absolute path: %r" % (target,))

    # BUG: blacklist instead of allow-list.
    if parsed.scheme in _DANGEROUS_SCHEMES:
        raise ValueError("redirect scheme is not allowed: %r" % (target,))

    if not parsed.netloc:
        raise ValueError("redirect target must have a host: %r" % (target,))

    if parsed.hostname != allowed_host:
        raise ValueError(
            "redirect host %r does not match allowed host %r"
            % (parsed.hostname, allowed_host)
        )

    return target
