class Query:
    """A fluent builder for simple SELECT statements.

    SEMANTIC MUTANT: where() defensively skips recording a falsy (empty
    string) condition instead of always recording every call. Per the
    contract, whether the WHERE clause is emitted depends on whether where()
    was CALLED at least once, not on whether the condition string is
    non-empty -- so where("") should still contribute a WHERE clause.
    """

    def __init__(self):
        self._columns = []
        self._wheres = []
        self._limit = None

    def select(self, *columns):
        self._columns.extend(columns)
        return self

    def where(self, condition):
        if condition:  # BUG: drops falsy (empty-string) conditions
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
