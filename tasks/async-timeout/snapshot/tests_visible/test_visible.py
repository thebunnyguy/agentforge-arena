"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only check that an instantly-resolving
coroutine returns its value — to demonstrate why the hidden tests, which assert
the timeout path and cancellation, are what actually grade.
"""

import asyncio

from atimeout import with_timeout


def _instant_factory(value):
    def make():
        async def run():
            return value

        return run()

    return make


def test_instant_coro_returns_value():
    result = asyncio.run(with_timeout(_instant_factory(123), seconds=1.0))
    assert result == 123
