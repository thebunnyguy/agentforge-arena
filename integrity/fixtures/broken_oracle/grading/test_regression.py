from pkg import is_valid_username


def test_ok_username_stable():
    assert is_valid_username("ok") is True
