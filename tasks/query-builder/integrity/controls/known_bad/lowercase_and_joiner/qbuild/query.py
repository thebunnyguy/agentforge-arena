class Query:
    """A fluent builder for simple SELECT statements.

    KNOWN-BAD CONTROL: WHERE conditions are joined with lowercase " and "
    instead of the contract-required " AND ". Every other clause (column
    joining, the "SELECT *" default, WHERE/LIMIT omission rules) is
    implemented correctly.
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
            sql += " WHERE " + " and ".join(self._wheres)  # BUG: lowercase "and"
        if self._limit is not None:
            sql += " LIMIT " + str(self._limit)
        return sql
