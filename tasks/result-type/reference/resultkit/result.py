class Result:
    """A success/error container in the style of Rust's ``Result``.

    Contract:
      * ``Result.ok(value)`` builds a success result holding ``value``.
      * ``Result.err(error)`` builds an error result holding ``error``.
      * ``is_ok`` is ``True`` for ok results, ``False`` for err results.
      * ``unwrap()`` returns the held value for an ok result; raises
        ``ValueError`` for an err result.
      * ``unwrap_or(default)`` returns the held value for an ok result;
        returns ``default`` for an err result.
      * ``map(fn)`` returns a NEW ok result holding ``fn(value)`` for an ok
        result; for an err result it is a no-op that returns an equivalent
        err result WITHOUT calling ``fn``.
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
        if self._is_ok:
            return Result.ok(fn(self._value))
        return Result.err(self._error)
