"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only check the trivial first-try-success
case — to demonstrate why the hidden tests, which assert the retry behavior and
last-exception re-raise, are what actually grade.
"""

import asyncio

from aretry import retry_call


def _ok_factory(value):
    def make():
        async def run():
            await asyncio.sleep(0)
            return value

        return run()

    return make


def test_returns_value_on_first_success():
    result = asyncio.run(retry_call(_ok_factory(42), attempts=3))
    assert result == 42
