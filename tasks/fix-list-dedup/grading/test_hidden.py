"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. The order-preservation cases fail with a set()-based dedup and pass
only with a first-occurrence-order-preserving implementation."""

from listkit import dedup


def test_preserves_first_occurrence_order_ints():
    assert dedup([3, 1, 3, 2, 1]) == [3, 1, 2]


def test_preserves_first_occurrence_order_strings():
    assert dedup(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_longer_sequence_order():
    assert dedup([5, 4, 5, 3, 4, 2, 1, 1]) == [5, 4, 3, 2, 1]


def test_empty_list():
    assert dedup([]) == []


def test_already_unique_preserved():
    assert dedup([10, 20, 30]) == [10, 20, 30]


def test_element_appearing_three_or_more_times():
    # A "skip the 2nd occurrence only" bug passes the at-most-twice cases but
    # lets a 3rd occurrence through.
    assert dedup([1, 2, 1, 2, 1]) == [1, 2]
    assert dedup([1, 1, 1]) == [1]
    assert dedup([1, 2, 1, 3, 1]) == [1, 2, 3]


# --- Order-discriminating cases (audit hardening) --------------------------
#
# The two tests above (`test_already_unique_preserved`,
# `test_element_appearing_three_or_more_times`) and `test_empty_list` all
# happen to use small, already-*ascending* integer values. CPython's `set()`
# places small non-negative ints at slot `hash(i) % table_size`, so for a
# handful of small distinct ints the resulting iteration order comes out
# ascending "for free" -- an implementation accident of CPython, not a
# property of correctness. That means a broken `list(set(items))` dedup
# (exactly the bug this task asks to fix) coincidentally produces the RIGHT
# answer on those three cases even though it is not preserving
# first-occurrence order at all. Verified by hand: with the fixed hash seed
# the grading sandbox uses (PYTHONHASHSEED=0, see afa_runner/sandbox.py),
# `list(set([10, 20, 30]))` and `list(set([1, 2, 1, 2, 1]))` etc. all land
# back on the "expected" ascending answer. Those tests are kept (they still
# catch element-dropping/crash bugs), but they provide ZERO signal against
# THIS task's actual bug, which is what let the unmodified snapshot bank
# T_hidden=0.500 despite doing nothing (see integrity/pack-audit).
#
# The two tests below enforce the exact same documented contract --
# "distinct elements, in order of first appearance" -- but pick values whose
# correct first-occurrence order is a NON-ascending permutation, so no
# implementation that reorders elements via ascending-ish set/hash iteration
# (or via sorting, or any other order not tied to first appearance) can pass
# by accident. Any conforming implementation (the reference's seen-set scan,
# a manual O(n^2) scan, `list(dict.fromkeys(items))`, ...) passes regardless
# of the values chosen, because none of those approaches depend on hash
# iteration order for their output order.


def test_no_duplicates_preserved_when_nonascending():
    # Semantic property: when a list already has no duplicates, the "in
    # order of first appearance" contract reduces to "return the input
    # unchanged" -- there is nothing to remove, so nothing may be reordered
    # either. `test_already_unique_preserved` uses (10, 20, 30), which is
    # already ascending, so a buggy dedup that silently reorders through
    # set() still lands on the same ascending answer by coincidence. Using
    # unique values that are NOT already ascending removes that coincidence:
    # only an implementation that truly leaves an already-unique list's
    # order alone can pass.
    assert dedup([30, 10, 20]) == [30, 10, 20]


def test_repeated_element_survives_multiple_times_nonascending_order():
    # Semantic property: same as test_element_appearing_three_or_more_times
    # (an element seen 3+ times must collapse to exactly one occurrence,
    # positioned at its FIRST appearance) but with values whose correct
    # first-occurrence order is not the same as ascending numeric order, so
    # a set()-based (or otherwise order-scrambling) dedup cannot pass by
    # coincidentally matching ascending order the way it does on (1, 2, 3).
    assert dedup([7, 3, 7, 3, 7]) == [7, 3]
    assert dedup([40, 10, 40, 25, 40]) == [40, 10, 25]
    assert dedup([6, 1, 6, 4, 6]) == [6, 1, 4]
