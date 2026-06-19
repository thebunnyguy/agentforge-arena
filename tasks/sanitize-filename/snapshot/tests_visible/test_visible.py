"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they pass even with the buggy pass-through
implementation — to demonstrate why hidden tests are what actually grade.
"""

from safename import safe_name


def test_plain_name_returned():
    assert safe_name("report.txt") == "report.txt"


def test_returns_a_string():
    assert isinstance(safe_name("data.csv"), str)
