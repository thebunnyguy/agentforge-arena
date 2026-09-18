"""Hidden tests: DELIBERATELY contradicts the task description (double(n) ==
n*2). test_contradiction requires double(5) == 12, which no correct
implementation of "n * 2" can satisfy (5*2 == 10, not 12) — this fixture
represents an impossible/unsolvable task, which the reference-solution check
must catch."""

from pkg import double


def test_basic_double():
    assert double(2) == 4


def test_contradiction():
    assert double(5) == 12
