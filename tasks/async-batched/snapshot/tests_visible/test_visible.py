"""Visible tests: the agent's feedback signal (NOT scored).

These give useful contract feedback without exposing the hidden concurrency and
batch-boundary probes that provide the real grading signal.
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
    assert result == [1, 2, 3]


def test_empty_input_returns_empty_list():
    assert asyncio.run(run_in_batches([], batch_size=3)) == []


def test_single_factory_result():
    assert asyncio.run(run_in_batches([_factory("ok")], batch_size=1)) == ["ok"]
