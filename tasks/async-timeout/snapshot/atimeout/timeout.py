async def with_timeout(make_coro, seconds):
    """Await a coroutine with a timeout.

    ``make_coro`` is a zero-argument callable that returns a fresh coroutine.
    Await that coroutine: if it finishes within ``seconds`` seconds, return its
    result. If it does not finish in time, raise ``TimeoutError`` and ensure the
    coroutine is cancelled so no task is left running.

    STUB: not implemented yet.
    """
    raise NotImplementedError("with_timeout is not implemented yet")
