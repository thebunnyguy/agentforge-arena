from pkg import is_adult


def test_is_adult_returns_bool():
    assert isinstance(is_adult(20), bool)
