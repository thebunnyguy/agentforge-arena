import re

REDACTED = "[REDACTED]"

_API_KEY = re.compile(r"sk-[A-Za-z0-9]{20,}")

# BUG: quantifier reversed. The spec wants "8 or more" characters (>= 8), but
# {1,8} caps the match at 8 characters, so anything past the 8th character of
# a longer token is left dangling in the output, unredacted.
_BEARER = re.compile(r"Bearer\s+\S{1,8}")

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask(text):
    """Return ``text`` with secrets replaced by the literal ``"[REDACTED]"``."""
    text = _API_KEY.sub(REDACTED, text)
    text = _BEARER.sub(REDACTED, text)
    text = _EMAIL.sub(REDACTED, text)
    return text
