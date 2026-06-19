"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only check angle-bracket escaping, which the
buggy snapshot already handles — to demonstrate why hidden tests are what
actually grade.
"""

from htmlesc import escape


def test_escapes_angle_brackets():
    assert escape("<script>") == "&lt;script&gt;"


def test_plain_text_unchanged():
    assert escape("hello world") == "hello world"
