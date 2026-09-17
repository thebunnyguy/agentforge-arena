class Result:
    """A success/error container in the style of Rust's ``Result``.

    ALTERNATIVE (structurally different, behaviorally equivalent) design:
    rather than one class carrying an is_ok flag plus value/error slots, the
    ok/err cases are two subclasses (_Ok/_Err) sharing this common interface.
    Result.ok()/Result.err() are factories that build the right subclass, and
    each method is implemented per-subclass instead of branching on a flag.
    """

    @classmethod
    def ok(cls, value):
        return _Ok(value)

    @classmethod
    def err(cls, error):
        return _Err(error)

    @property
    def is_ok(self):  # pragma: no cover - overridden by both subclasses
        raise NotImplementedError

    def unwrap(self):  # pragma: no cover - overridden by both subclasses
        raise NotImplementedError

    def unwrap_or(self, default):  # pragma: no cover - overridden
        raise NotImplementedError

    def map(self, fn):  # pragma: no cover - overridden by both subclasses
        raise NotImplementedError


class _Ok(Result):
    def __init__(self, value):
        self._value = value

    @property
    def is_ok(self):
        return True

    def unwrap(self):
        return self._value

    def unwrap_or(self, default):
        return self._value

    def map(self, fn):
        return _Ok(fn(self._value))


class _Err(Result):
    def __init__(self, error):
        self._error = error

    @property
    def is_ok(self):
        return False

    def unwrap(self):
        raise ValueError(f"called unwrap on an err result: {self._error!r}")

    def unwrap_or(self, default):
        return default

    def map(self, fn):
        # No-op: return an equivalent err result WITHOUT calling fn.
        return _Err(self._error)
