"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they pass even with the buggy set()-based
implementation — to demonstrate why hidden tests are what actually grade.
"""

from listkit import dedup


def test_removes_duplicates_as_a_set():
    assert set(dedup([1, 1, 2, 3, 3])) == {1, 2, 3}


def test_returns_a_list():
    assert isinstance(dedup([1, 2, 2]), list)
