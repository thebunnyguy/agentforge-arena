"""Regression tests: pre-existing behavior that must keep working. These test
the stable sibling ``chunk`` (and a trivial import contract true in both the
snapshot and the reference). They pass on the unmodified snapshot AND after a
correct implementation; a change that breaks them fails the regression gate."""

import inspect

import pytest

from abatch import chunk, run_in_batches


def test_chunk_even_split():
    assert chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]


def test_chunk_uneven_split_has_short_tail():
    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunk_size_larger_than_seq():
    assert chunk([1, 2], 5) == [[1, 2]]


def test_chunk_accepts_tuple_without_mutating_input():
    values = (1, 2, 3, 4, 5)
    assert chunk(values, 2) == [[1, 2], [3, 4], [5]]
    assert values == (1, 2, 3, 4, 5)


def test_chunk_empty_seq():
    assert chunk([], 3) == []


def test_chunk_rejects_nonpositive_size():
    with pytest.raises(ValueError):
        chunk([1, 2, 3], 0)


def test_run_in_batches_is_a_coroutine_function():
    # Trivial contract true in both snapshot (stub) and reference: the public
    # entry point exists and is async. Calling it is left to the hidden suite.
    assert inspect.iscoroutinefunction(run_in_batches)
