class Query:
    """A fluent builder for simple SELECT statements.

    ALTERNATIVE (structurally different, behaviorally equivalent): build()
    assembles a list of already-formatted clause strings and joins them with
    a single space at the end, rather than incrementally concatenating onto a
    running "sql" string.
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
        clauses = []

        if self._columns:
            clauses.append("SELECT " + ", ".join(self._columns))
        else:
            clauses.append("SELECT *")

        if self._wheres:
            clauses.append("WHERE " + " AND ".join(self._wheres))

        if self._limit is not None:
            clauses.append("LIMIT " + str(self._limit))

        return " ".join(clauses)
