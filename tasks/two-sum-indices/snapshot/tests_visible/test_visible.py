"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only check a coarse property of the result —
to demonstrate why the hidden tests are what actually grade.
"""

from twosum import two_sum


def test_returns_tuple_or_none():
    result = two_sum([2, 7, 11, 15], 9)
    assert result is None or isinstance(result, tuple)


def test_finds_a_pair():
    assert two_sum([2, 7, 11, 15], 9) == (0, 1)
