class Result:
    """A success/error container in the style of Rust's ``Result``.

    SEMANTIC MUTANT: map() on an ok result mutates self in place and returns
    self, instead of constructing a NEW ok Result as the contract requires.
    Observable via unwrap()/is_ok on the returned object it is
    indistinguishable from a correct implementation; it only differs if a
    caller keeps a reference to the original Result and observes it change
    out from under them (an aliasing bug the contract explicitly rules out
    by saying map "returns a NEW ok Result").
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
            # BUG: mutates self in place and returns self instead of
            # building a NEW ok Result.
            self._value = fn(self._value)
            return self
        return Result.err(self._error)
