class Result:
    """A success/error container in the style of Rust's ``Result``.

    KNOWN-BAD CONTROL: unwrap_or()'s is_ok branch is reversed, so it returns
    the default for an ok result and the (missing) value for an err result.
    Everything else matches the correct implementation.
    """

    def __init__(self, is_ok, value=None, error=None):
        self._is_ok = is_ok
        self._value = value
        self._error = error

    @classmethod
    def ok(cls, value):
        return cls(True, value=value)

    @classmethod
    def err(cls, error):
        return cls(False, error=error)

    @property
    def is_ok(self):
        return self._is_ok

    def unwrap(self):
        if self._is_ok:
            return self._value
        raise ValueError(f"called unwrap on an err result: {self._error!r}")

    def unwrap_or(self, default):
        # BUG: branches reversed — ok returns default, err returns _value.
        if self._is_ok:
            return default
        return self._value

    def map(self, fn):
        if self._is_ok:
            return Result.ok(fn(self._value))
        return Result.err(self._error)
