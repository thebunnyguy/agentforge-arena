from pkg import is_valid_username


def test_valid_username_returns_bool():
    assert isinstance(is_valid_username("abc"), bool)
