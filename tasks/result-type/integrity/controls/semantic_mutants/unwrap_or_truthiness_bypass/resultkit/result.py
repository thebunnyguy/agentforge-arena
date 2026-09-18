class Result:
    """A success/error container in the style of Rust's ``Result``.

    SEMANTIC MUTANT: unwrap_or() checks the truthiness of the stored value
    instead of the is_ok flag. This is indistinguishable from a correct
    implementation for any ok result holding a truthy value (and for err
    results, whose value happens to be None/falsy too) — it only misbehaves
    on falsy ok values (0, None, False), which the contract explicitly
    requires to still count as success.
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
        # BUG: branches on the truthiness of the stored value, not is_ok.
        # Correct for ok(<truthy>) and err(...) (whose _value is None), but
        # wrong for ok(0), ok(None), ok(False).
        return self._value if self._value else default

    def map(self, fn):
        if self._is_ok:
            return Result.ok(fn(self._value))
        return Result.err(self._error)
