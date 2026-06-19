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

    STUB: the constructors and methods are not implemented yet.
    """

    @classmethod
    def ok(cls, value):
        raise NotImplementedError("Result.ok is not implemented yet")

    @classmethod
    def err(cls, error):
        raise NotImplementedError("Result.err is not implemented yet")

    @property
    def is_ok(self):
        raise NotImplementedError("Result.is_ok is not implemented yet")

    def unwrap(self):
        raise NotImplementedError("Result.unwrap is not implemented yet")

    def unwrap_or(self, default):
        raise NotImplementedError("Result.unwrap_or is not implemented yet")

    def map(self, fn):
        raise NotImplementedError("Result.map is not implemented yet")
