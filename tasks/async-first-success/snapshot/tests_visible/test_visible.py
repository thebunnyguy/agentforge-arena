"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only check that a single successful coroutine
returns its value — to demonstrate why the hidden tests, which assert
first-success selection and cancellation of the losers, are what actually grade.
"""

import asyncio

from afirst import first_success


def _ok_factory(value):
    def make():
        async def run():
            await asyncio.sleep(0)
            return value

        return run()

    return make


def test_single_success_returns_value():
    result = asyncio.run(first_success([_ok_factory(5)]))
    assert result == 5
