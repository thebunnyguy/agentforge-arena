"""Hidden tests: the graded correctness signal. Covers the exact boundary
(n == 10) the snapshot's off-by-one bug misclassifies."""

from pkg import classify


def test_small_values():
    assert classify(0) == "small"
    assert classify(5) == "small"
    assert classify(9) == "small"


def test_boundary_value_is_large():
    assert classify(10) == "large"


def test_large_values():
    assert classify(11) == "large"
    assert classify(100) == "large"


def test_negative_is_small():
    assert classify(-5) == "small"
