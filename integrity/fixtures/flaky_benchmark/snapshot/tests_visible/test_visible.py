from pkg import add_one


def test_add_one_returns_int():
    assert isinstance(add_one(1), int)
