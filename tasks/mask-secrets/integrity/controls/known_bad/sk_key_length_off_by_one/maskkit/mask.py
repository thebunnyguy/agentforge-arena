import re

REDACTED = "[REDACTED]"

# BUG: off-by-one. The spec says "20 or more alphanumeric characters" (>= 20),
# but this requires strictly more than 20, so a 20-character key slips through.
_API_KEY = re.compile(r"sk-[A-Za-z0-9]{21,}")

_BEARER = re.compile(r"Bearer\s+\S{8,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask(text):
    """Return ``text`` with secrets replaced by the literal ``"[REDACTED]"``."""
    text = _API_KEY.sub(REDACTED, text)
    text = _BEARER.sub(REDACTED, text)
    text = _EMAIL.sub(REDACTED, text)
    return text
