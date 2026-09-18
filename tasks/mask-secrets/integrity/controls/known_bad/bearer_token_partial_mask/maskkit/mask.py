import re

REDACTED = "[REDACTED]"

_API_KEY = re.compile(r"sk-[A-Za-z0-9]{20,}")

# BUG: a lookbehind keeps the "Bearer " keyword out of the match, so it stays
# visible in the output instead of being redacted along with the token.
_BEARER = re.compile(r"(?<=Bearer )\S{8,}")

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask(text):
    """Return ``text`` with secrets replaced by the literal ``"[REDACTED]"``."""
    text = _API_KEY.sub(REDACTED, text)
    text = _BEARER.sub(REDACTED, text)
    text = _EMAIL.sub(REDACTED, text)
    return text
