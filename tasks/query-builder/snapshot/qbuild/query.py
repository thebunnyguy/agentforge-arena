class Query:
    """A fluent builder for simple SELECT statements.

    Contract:
      * ``Query()`` starts an empty builder.
      * ``select(*columns)`` records the selected columns and returns self.
      * ``where(condition)`` appends a WHERE condition and returns self; it may
        be called multiple times.
      * ``limit(n)`` records a row limit and returns self.
      * ``build()`` returns the SQL string in the order
        ``SELECT ... [WHERE ...] [LIMIT n]``:
          - SELECT clause is ``"SELECT *"`` when no columns were selected,
            otherwise ``"SELECT "`` + columns joined with ``", "``.
          - the ``" WHERE "`` clause (conditions joined with ``" AND "``) is
            appended only if at least one ``where()`` was called.
          - ``" LIMIT n"`` is appended only if ``limit()`` was called.

    STUB: chaining and build() are not implemented yet.
    """

    def __init__(self):
        self._columns = []
        self._wheres = []
        self._limit = None

    def select(self, *columns):
        raise NotImplementedError("Query.select is not implemented yet")

    def where(self, condition):
        raise NotImplementedError("Query.where is not implemented yet")

    def limit(self, n):
        raise NotImplementedError("Query.limit is not implemented yet")

    def build(self):
        raise NotImplementedError("Query.build is not implemented yet")
