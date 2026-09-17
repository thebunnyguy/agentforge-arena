from pkg import double


def test_double_returns_int():
    assert isinstance(double(3), int)
