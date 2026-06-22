"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These fail on the stub (NotImplementedError) and pass only with a
correct fluent builder that produces the exact SQL strings."""

from qbuild import Query


def test_full_example():
    sql = Query().select("a", "b").where("x=1").where("y=2").limit(10).build()
    assert sql == "SELECT a, b WHERE x=1 AND y=2 LIMIT 10"


def test_select_star_default():
    assert Query().build() == "SELECT *"


def test_single_column_no_where_no_limit():
    assert Query().select("id").build() == "SELECT id"


def test_two_wheres_and_joined():
    sql = Query().select("a").where("x=1").where("y=2").build()
    assert sql == "SELECT a WHERE x=1 AND y=2"


def test_limit_without_where():
    sql = Query().select("a", "b").limit(5).build()
    assert sql == "SELECT a, b LIMIT 5"


def test_where_without_limit():
    sql = Query().select("a").where("x=1").build()
    assert sql == "SELECT a WHERE x=1"


def test_methods_return_self_for_chaining():
    q = Query()
    assert q.select("a") is q
    assert q.where("x=1") is q
    assert q.limit(3) is q


def test_select_star_still_appends_where_and_limit():
    # The default "SELECT *" branch must not drop accumulated WHERE/LIMIT clauses.
    assert Query().where("a=1").limit(5).build() == "SELECT * WHERE a=1 LIMIT 5"
