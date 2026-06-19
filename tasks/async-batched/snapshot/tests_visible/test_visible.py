"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only check a trivial run and the empty input
— to demonstrate why the hidden tests, which assert input ordering and the
per-batch concurrency bound, are what actually grade.
"""

import asyncio

from abatch import run_in_batches


def _factory(value):
    def make():
        async def run():
            await asyncio.sleep(0)
            return value

        return run()

    return make


def test_runs_and_returns_values():
    result = asyncio.run(
        run_in_batches([_factory(1), _factory(2), _factory(3)], batch_size=2)
    )
    assert sorted(result) == [1, 2, 3]


def test_empty_input_returns_empty_list():
    assert asyncio.run(run_in_batches([], batch_size=3)) == []
