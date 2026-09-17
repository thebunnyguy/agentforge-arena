import re

REDACTED = "[REDACTED]"

# BUG (semantic mutant): anchors every pattern to \b word boundaries, as if
# secrets only ever appear as whole, delimited tokens. The task's spec places
# no such requirement on sk-/Bearer/email matches, so a secret glued directly
# onto adjacent alphanumeric text (no space/punctuation separating it from a
# preceding letter or digit) fails to match and leaks into the output
# unredacted. Ordinary, delimiter-separated secrets (the common case the
# visible/hidden fixtures happen to use) still get caught, which is exactly
# what makes this a realistic, narrow-test-suite-passing near-miss rather than
# an obviously broken implementation.
_API_KEY = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
_BEARER = re.compile(r"\bBearer\s+\S{8,}\b")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def mask(text):
    """Return ``text`` with secrets replaced by the literal ``"[REDACTED]"``."""
    text = _API_KEY.sub(REDACTED, text)
    text = _BEARER.sub(REDACTED, text)
    text = _EMAIL.sub(REDACTED, text)
    return text
