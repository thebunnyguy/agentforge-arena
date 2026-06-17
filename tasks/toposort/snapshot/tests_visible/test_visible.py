"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only check coarse properties of the result —
to demonstrate why the hidden tests are what actually grade.
"""

from graphkit import toposort


def test_returns_a_list():
    assert isinstance(toposort({"a": [], "b": ["a"]}), list)


def test_contains_every_node():
    assert sorted(toposort({"a": [], "b": ["a"]})) == ["a", "b"]
