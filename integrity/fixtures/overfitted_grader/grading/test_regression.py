from pkg import require_non_negative


def test_zero_passes():
    assert require_non_negative(0) == 0
