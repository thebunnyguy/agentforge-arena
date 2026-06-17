"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only check the easy cases (a trivial run and
the empty input) — to demonstrate why the hidden tests, which assert ordering
and the concurrency bound, are what actually grade.
"""

import asyncio

from asynckit import gather_bounded


def _factory(value):
    async def run():
        await asyncio.sleep(0)
        return value

    return run


def test_runs_and_returns_values():
    result = asyncio.run(gather_bounded([_factory(1), _factory(2)], limit=2))
    assert sorted(result) == [1, 2]


def test_empty_input_returns_empty_list():
    assert asyncio.run(gather_bounded([], limit=3)) == []
