import asyncio


async def first_success(make_coros):
    """Return the result of the first coroutine to succeed.

    ``make_coros`` is a list of zero-argument callables, each returning a fresh
    coroutine when called. Run them all concurrently. Return the result of the
    first coroutine that completes successfully and cancel the rest. If every
    coroutine fails, raise the last exception (the exception raised by the last
    factory in input order). ``make_coros`` must be non-empty.
    """
    factories = list(make_coros)
    if not factories:
        raise ValueError("make_coros must be non-empty")

    tasks = [asyncio.ensure_future(make()) for make in factories]
    index_of = {task: i for i, task in enumerate(tasks)}
    errors = [None] * len(tasks)  # exception per input index, if that task failed

    async def _cancel_all():
        for task in tasks:
            task.cancel()
        # Let every cancellation settle so no task is left pending.
        await asyncio.gather(*tasks, return_exceptions=True)

    pending = set(tasks)
    try:
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                exc = task.exception()
                if exc is None:
                    result = task.result()
                    await _cancel_all()
                    return result
                errors[index_of[task]] = exc
    except BaseException:
        await _cancel_all()
        raise

    # No task succeeded: re-raise the last factory's exception (input order).
    raise errors[-1]
