"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only check the page count for one clean case
and that page(1) starts at 0 — so they say nothing about end_index, the
has_previous/has_next flags, or the out-of-range ValueError behavior. The hidden
tests are what actually grade the implementation.
"""

from paginate import Paginator


def test_num_pages_basic():
    assert Paginator(10, 3).num_pages == 4


def test_first_page_starts_at_zero():
    assert Paginator(10, 3).page(1).start_index == 0
