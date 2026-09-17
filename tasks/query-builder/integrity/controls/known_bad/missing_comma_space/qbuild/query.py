class Query:
    """A fluent builder for simple SELECT statements.

    KNOWN-BAD CONTROL: the column list is joined with a bare comma instead of
    ", " (comma + space). Every other clause (WHERE, AND-joining, LIMIT,
    the "SELECT *" default) is implemented correctly.
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
            sql = "SELECT " + ",".join(self._columns)  # BUG: missing space after comma
        else:
            sql = "SELECT *"
        if self._wheres:
            sql += " WHERE " + " AND ".join(self._wheres)
        if self._limit is not None:
            sql += " LIMIT " + str(self._limit)
        return sql
