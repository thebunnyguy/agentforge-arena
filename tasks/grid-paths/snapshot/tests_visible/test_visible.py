"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only check a couple of tiny grids — to
demonstrate why the hidden tests are what actually grade.
"""

from gridpaths import count_paths


def test_single_cell():
    assert count_paths(1, 1) == 1


def test_two_by_two():
    assert count_paths(2, 2) == 2
