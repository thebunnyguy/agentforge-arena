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
    """

    def __init__(self):
        self._columns = []
        self._wheres = []
        self._limit = None

    def select(self, *columns):
        self._columns.extend(columns)
        return self

    def where(self, condition):
        self._wheres.append(condition)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def build(self):
        if self._columns:
            sql = "SELECT " + ", ".join(self._columns)
        else:
            sql = "SELECT *"
        if self._wheres:
            sql += " WHERE " + " AND ".join(self._wheres)
        if self._limit is not None:
            sql += " LIMIT " + str(self._limit)
        return sql
