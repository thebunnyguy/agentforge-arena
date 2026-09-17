class Query:
    """A fluent builder for simple SELECT statements.

    KNOWN-BAD CONTROL: the "no columns selected" branch returns early with a
    bare "SELECT *" and never appends accumulated WHERE/LIMIT clauses, because
    that logic was written only inside the "columns present" branch instead of
    being shared by both.
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
            if self._wheres:
                sql += " WHERE " + " AND ".join(self._wheres)
            if self._limit is not None:
                sql += " LIMIT " + str(self._limit)
            return sql
        # BUG: forgets to also apply the WHERE/LIMIT logic above when no
        # columns were selected.
        return "SELECT *"
