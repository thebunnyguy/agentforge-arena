"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only check that build() mentions the chosen
column and that chaining returns something usable — so they say nothing about
the exact clause formatting, AND-joining, or omission rules. The hidden tests
are what actually grade the implementation.
"""

from qbuild import Query


def test_select_mentions_column():
    sql = Query().select("a").build()
    assert "a" in sql


def test_build_returns_str():
    assert isinstance(Query().build(), str)
