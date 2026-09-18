from pkg import require_non_negative


def test_positive_passes_through():
    assert require_non_negative(3) == 3
