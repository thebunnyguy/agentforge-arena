"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they pass even with the buggy naive-join
implementation — to demonstrate why hidden tests are what actually grade.
"""

from safepath import safe_join


def test_simple_nested_join_returns_string():
    assert isinstance(safe_join("/srv/data", "reports"), str)


def test_simple_nested_join_stays_under_base():
    assert safe_join("/srv/data", "reports", "q1.csv") == "/srv/data/reports/q1.csv"
