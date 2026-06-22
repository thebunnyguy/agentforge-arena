"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These exercise the full toposort contract — dependency ordering,
deterministic lexicographic tiebreaks, and cycle detection — and fail against
the unimplemented stub."""

import pytest

from graphkit import CycleError, toposort


def _before(order, dep, node):
    """True iff ``dep`` appears before ``node`` in ``order``."""
    return order.index(dep) < order.index(node)


def test_linear_chain():
    # c depends on b depends on a -> a, b, c
    graph = {"c": ["b"], "b": ["a"], "a": []}
    assert toposort(graph) == ["a", "b", "c"]


def test_diamond_respects_dependencies():
    # d depends on b and c; b and c each depend on a.
    graph = {"d": ["b", "c"], "b": ["a"], "c": ["a"], "a": []}
    order = toposort(graph)
    assert sorted(order) == ["a", "b", "c", "d"]
    assert _before(order, "a", "b")
    assert _before(order, "a", "c")
    assert _before(order, "b", "d")
    assert _before(order, "c", "d")


def test_diamond_is_deterministic_lexicographic():
    graph = {"d": ["b", "c"], "b": ["a"], "c": ["a"], "a": []}
    # b and c are both eligible after a; lexicographic tiebreak -> b before c.
    assert toposort(graph) == ["a", "b", "c", "d"]


def test_independent_nodes_sorted_lexicographically():
    graph = {"b": [], "a": [], "c": []}
    assert toposort(graph) == ["a", "b", "c"]


def test_tiebreak_prefers_lexicographic_among_eligible():
    # After "root", both "alpha" and "zeta" become eligible; alpha first.
    graph = {"root": [], "zeta": ["root"], "alpha": ["root"]}
    assert toposort(graph) == ["root", "alpha", "zeta"]


def test_cycle_raises():
    graph = {"a": ["b"], "b": ["a"]}
    with pytest.raises(CycleError):
        toposort(graph)


def test_self_loop_raises():
    graph = {"a": ["a"]}
    with pytest.raises(CycleError):
        toposort(graph)


def test_longer_cycle_raises():
    graph = {"a": ["b"], "b": ["c"], "c": ["a"]}
    with pytest.raises(CycleError):
        toposort(graph)


def test_disconnected_components():
    # Two independent chains: a<-b and x<-y.
    graph = {"b": ["a"], "a": [], "y": ["x"], "x": []}
    order = toposort(graph)
    assert sorted(order) == ["a", "b", "x", "y"]
    assert _before(order, "a", "b")
    assert _before(order, "x", "y")


def test_empty_graph():
    assert toposort({}) == []


def test_node_with_no_deps_implicit():
    # "lib" appears only as a dependency and has no key of its own.
    graph = {"app": ["lib"]}
    order = toposort(graph)
    assert sorted(order) == ["app", "lib"]
    assert _before(order, "lib", "app")


def test_implicit_dependency_in_cycle_is_still_a_cycle():
    # b depends on a; a depends on b but a has no explicit key — still a cycle.
    graph = {"b": ["a"], "a": ["b"]}
    with pytest.raises(CycleError):
        toposort(graph)


def test_multiple_implicit_dependencies():
    # Both "lib" and "core" appear only as dependencies (no key of their own); an
    # impl that registers only the FIRST implicit dep of each list misses "core".
    graph = {"app": ["lib", "core"]}
    order = toposort(graph)
    assert sorted(order) == ["app", "core", "lib"]
    assert _before(order, "lib", "app")
    assert _before(order, "core", "app")
