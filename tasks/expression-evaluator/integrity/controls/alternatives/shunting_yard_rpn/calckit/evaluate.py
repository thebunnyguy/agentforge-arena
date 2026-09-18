def evaluate(expr):
    """Evaluate an arithmetic expression string and return the result as a float.

    Supports ``+``, ``-``, ``*``, ``/``, parentheses, correct operator
    precedence, unary minus, integer and float literals, and arbitrary
    whitespace.

    Implemented with the shunting-yard algorithm: tokens are converted to
    Reverse Polish Notation (with unary ``+``/``-`` promoted to distinct,
    higher-precedence, right-associative pseudo-operators so they bind only
    to the single operand that follows them) and the RPN is then evaluated
    with one value stack. This is structurally unrelated to a recursive-
    descent grammar, but computes the same results. No ``eval``.
    """
    tokens = _tokenize(expr)
    rpn = _to_rpn(tokens, expr)
    return float(_eval_rpn(rpn, expr))


def _tokenize(expr):
    tokens = []
    i = 0
    n = len(expr)
    while i < n:
        c = expr[i]
        if c.isspace():
            i += 1
            continue
        if c in "+-*/()":
            tokens.append(c)
            i += 1
            continue
        if c.isdigit() or c == ".":
            j = i
            seen_dot = False
            while j < n and (expr[j].isdigit() or expr[j] == "."):
                if expr[j] == ".":
                    if seen_dot:
                        raise ValueError("invalid number literal in %r" % expr)
                    seen_dot = True
                j += 1
            tokens.append(expr[i:j])
            i = j
            continue
        raise ValueError("unexpected character %r in %r" % (c, expr))
    return tokens


_BINARY_PRECEDENCE = {"+": 1, "-": 1, "*": 2, "/": 2}
_UNARY_PRECEDENCE = {"u+": 3, "u-": 3}
_PRECEDENCE = {**_BINARY_PRECEDENCE, **_UNARY_PRECEDENCE}
_RIGHT_ASSOCIATIVE = {"u+", "u-"}
_OPERATOR_CHARS = ("+", "-", "*", "/")


def _is_number_token(tok):
    return tok not in _OPERATOR_CHARS and tok not in ("(", ")")


def _to_rpn(tokens, expr):
    output = []
    op_stack = []
    prev = None  # previous *emitted* token/marker, used to detect unary context

    def pop_while_higher_or_equal(op):
        while op_stack and op_stack[-1] != "(":
            top = op_stack[-1]
            if _PRECEDENCE[top] > _PRECEDENCE[op] or (
                _PRECEDENCE[top] == _PRECEDENCE[op] and op not in _RIGHT_ASSOCIATIVE
            ):
                output.append(op_stack.pop())
            else:
                break

    for tok in tokens:
        if _is_number_token(tok):
            output.append(tok)
            prev = tok
        elif tok == "(":
            op_stack.append(tok)
            prev = tok
        elif tok == ")":
            while op_stack and op_stack[-1] != "(":
                output.append(op_stack.pop())
            if not op_stack:
                raise ValueError("mismatched parentheses in %r" % expr)
            op_stack.pop()  # discard the matching '('
            prev = tok
        else:
            # tok is one of + - * /
            is_unary = tok in ("+", "-") and (
                prev is None or prev in _OPERATOR_CHARS or prev in _UNARY_PRECEDENCE or prev == "("
            )
            op = ("u" + tok) if is_unary else tok
            pop_while_higher_or_equal(op)
            op_stack.append(op)
            prev = op

    while op_stack:
        op = op_stack.pop()
        if op == "(":
            raise ValueError("mismatched parentheses in %r" % expr)
        output.append(op)
    return output


def _eval_rpn(rpn, expr):
    stack = []
    for tok in rpn:
        if tok in _BINARY_PRECEDENCE:
            if len(stack) < 2:
                raise ValueError("invalid expression %r" % expr)
            b = stack.pop()
            a = stack.pop()
            if tok == "+":
                stack.append(a + b)
            elif tok == "-":
                stack.append(a - b)
            elif tok == "*":
                stack.append(a * b)
            else:
                stack.append(a / b)
        elif tok in _UNARY_PRECEDENCE:
            if not stack:
                raise ValueError("invalid expression %r" % expr)
            a = stack.pop()
            stack.append(a if tok == "u+" else -a)
        else:
            stack.append(float(tok))
    if len(stack) != 1:
        raise ValueError("invalid expression %r" % expr)
    return stack[0]
