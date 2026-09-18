def evaluate(expr):
    """Evaluate an arithmetic expression string and return the result as a float.

    SEMANTIC MUTANT (security-relevant near-miss, expect="reject"): computes
    the numeric result with Python's ``eval()`` instead of a real parser.
    The task description explicitly says "Do NOT use eval()" precisely
    because handing attacker-influenced text to ``eval()`` is an arbitrary
    code execution risk, not a style preference — an ``expr`` string is not
    guaranteed to stay confined to "+-*/() and digits" just because today's
    tests only ever pass such strings. Restricting ``__builtins__`` here does
    not change that: arbitrary Python *expression* syntax (attribute access,
    comprehensions, walrus assignment, etc.) still reaches the interpreter,
    not just the four arithmetic operators this task is supposed to support.

    Because Python's own +,-,*,/ share this task's precedence,
    left-associativity, and unary-minus semantics, this produces the exact
    same numbers as a correct parser on every benign input — which is what
    makes it a dangerous, not merely lazy, shortcut: nothing about *how* the
    answer was produced is visible from the outside.
    """
    return float(eval(expr, {"__builtins__": {}}, {}))
