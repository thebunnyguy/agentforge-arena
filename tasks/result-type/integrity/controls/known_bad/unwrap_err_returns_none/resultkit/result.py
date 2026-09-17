class Result:
    """A success/error container in the style of Rust's ``Result``.

    KNOWN-BAD CONTROL: unwrap() never raises on an err result — it just
    returns the stored error value instead. Everything else matches the
    correct implementation.
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
        # BUG: should raise ValueError for an err result; instead it just
        # hands back the stored error (or None) like unwrap_or would.
        if self._is_ok:
            return self._value
        return self._error

    def unwrap_or(self, default):
        if self._is_ok:
            return self._value
        return default

    def map(self, fn):
        if self._is_ok:
            return Result.ok(fn(self._value))
        return Result.err(self._error)
