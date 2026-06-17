def evaluate(expr):
    """Evaluate an arithmetic expression string and return the result as a float.

    Supports ``+``, ``-``, ``*``, ``/``, parentheses, correct operator
    precedence, unary minus, integer and float literals, and arbitrary
    whitespace. Implemented as a recursive-descent parser (no ``eval``).
    """
    tokens = _tokenize(expr)
    parser = _Parser(tokens)
    result = parser.parse_expression()
    parser.expect_end()
    return float(result)


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


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def _peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def _next(self):
        tok = self._peek()
        self.pos += 1
        return tok

    def expect_end(self):
        if self.pos != len(self.tokens):
            raise ValueError("unexpected trailing tokens: %r" % self.tokens[self.pos:])

    def parse_expression(self):
        # expression := term (('+' | '-') term)*
        value = self.parse_term()
        while self._peek() in ("+", "-"):
            op = self._next()
            rhs = self.parse_term()
            if op == "+":
                value += rhs
            else:
                value -= rhs
        return value

    def parse_term(self):
        # term := factor (('*' | '/') factor)*
        value = self.parse_factor()
        while self._peek() in ("*", "/"):
            op = self._next()
            rhs = self.parse_factor()
            if op == "*":
                value *= rhs
            else:
                value /= rhs
        return value

    def parse_factor(self):
        # factor := ('+' | '-') factor | '(' expression ')' | number
        tok = self._peek()
        if tok == "+":
            self._next()
            return self.parse_factor()
        if tok == "-":
            self._next()
            return -self.parse_factor()
        if tok == "(":
            self._next()
            value = self.parse_expression()
            if self._next() != ")":
                raise ValueError("expected closing parenthesis")
            return value
        if tok is None:
            raise ValueError("unexpected end of expression")
        return self._parse_number(tok)

    def _parse_number(self, tok):
        if tok in ("+", "-", "*", "/", "(", ")"):
            raise ValueError("expected a number but found %r" % tok)
        self._next()
        return float(tok)
