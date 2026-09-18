"""Hidden tests: test_negative_error_message_exact is OVERFIT to the
reference's exact wording rather than the contract ("raises ValueError for
negative input") — this fixture's declared alternative solution (integrity/
controls/alternatives/iterative/) raises ValueError with different wording
and is legitimately correct, but gets rejected by this test."""

import pytest

from pkg import require_non_negative


def test_positive_returned_unchanged():
    assert require_non_negative(5) == 5


def test_negative_raises_value_error():
    with pytest.raises(ValueError):
        require_non_negative(-1)


def test_negative_error_message_exact():
    with pytest.raises(ValueError) as exc_info:
        require_non_negative(-1)
    assert str(exc_info.value) == "n must be non-negative"
