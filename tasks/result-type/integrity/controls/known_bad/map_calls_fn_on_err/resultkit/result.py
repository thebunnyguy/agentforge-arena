class Result:
    """A success/error container in the style of Rust's ``Result``.

    KNOWN-BAD CONTROL: map() forgets the is_ok guard and applies fn
    unconditionally, so an err result has fn called on it and is silently
    turned into a new ok result. Everything else matches the correct
    implementation.
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
        if self._is_ok:
            return self._value
        return default

    def map(self, fn):
        # BUG: no is_ok guard — fn is called even on an err result, and the
        # outcome is wrapped as a NEW ok result instead of staying an err.
        source = self._value if self._is_ok else self._error
        return Result.ok(fn(source))
