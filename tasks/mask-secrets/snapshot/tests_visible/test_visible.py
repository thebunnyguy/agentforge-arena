"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only check the redaction marker shows up for
one obvious secret — to demonstrate why hidden tests are what actually grade.
The stub raises NotImplementedError, so these fail until mask is implemented.
"""

from maskkit import mask


def test_email_is_masked():
    assert "[REDACTED]" in mask("contact a@b.com please")


def test_plain_text_has_no_marker():
    assert "[REDACTED]" not in mask("just an ordinary sentence")
