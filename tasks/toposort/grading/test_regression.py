"""Regression tests: pre-existing behavior that must keep working. These cover
the stable sibling ``all_nodes`` (already correct in the snapshot) plus trivial
contracts true in both the snapshot and the reference. They pass on the
unmodified snapshot AND after a correct implementation."""

from graphkit import all_nodes


def test_all_nodes_includes_keys_and_deps():
    graph = {"b": ["a"], "c": ["a", "b"]}
    assert all_nodes(graph) == ["a", "b", "c"]


def test_all_nodes_sorted():
    graph = {"z": [], "m": ["z"], "a": ["m"]}
    assert all_nodes(graph) == ["a", "m", "z"]


def test_all_nodes_empty_graph():
    assert all_nodes({}) == []


def test_all_nodes_returns_list():
    assert isinstance(all_nodes({"x": []}), list)
