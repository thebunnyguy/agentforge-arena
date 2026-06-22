"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These fail on the stub (NotImplementedError) and pass only with a
correct Paginator implementation, including the out-of-range ValueError and
empty-collection (num_pages == 0) behavior."""

import pytest

from paginate import Paginator


def test_num_pages_ceiling():
    assert Paginator(10, 3).num_pages == 4


def test_first_page_indices_and_flags():
    p = Paginator(10, 3).page(1)
    assert p.number == 1
    assert p.start_index == 0
    assert p.end_index == 3
    assert p.has_previous is False
    assert p.has_next is True


def test_last_page_indices_and_flags():
    p = Paginator(10, 3).page(4)
    assert p.number == 4
    assert p.start_index == 9
    assert p.end_index == 10
    assert p.has_previous is True
    assert p.has_next is False


def test_page_zero_raises():
    with pytest.raises(ValueError):
        Paginator(10, 3).page(0)


def test_page_beyond_last_raises():
    with pytest.raises(ValueError):
        Paginator(10, 3).page(5)


def test_empty_collection_has_no_pages():
    p = Paginator(0, 3)
    assert p.num_pages == 0
    with pytest.raises(ValueError):
        p.page(1)


def test_middle_page_flags():
    # A middle page has BOTH a previous and a next page (catches an off-by-one
    # has_next computed only correctly at the first/last page).
    p = Paginator(25, 10).page(2)   # page 2 of 3
    assert p.has_next is True
    assert p.has_previous is True
