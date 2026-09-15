"""Parser for the toy loop-IR text format.

Format (whitespace and ``#`` comments are ignored)::

    vector_width 4                       # optional, defaults to 4
    loop i = 0 to 100                    # iterations are start .. end-1
        y[i] = alpha * x[i] + y[i]
    end

Array indices are affine in the induction variable, for example ``i``,
``i-1``, ``i+1`` or ``2*i+1``. Statements are assignments to array
elements; the right-hand side may also use loop-invariant scalars and
function calls (calls are rejected later by the legality checker).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .ir import BinOp, Call, Expr, Index, Loop, Num, Ref, Scalar, Statement


class ParseError(Exception):
    """Raised when the input text cannot be parsed at all."""


_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<comment>\#[^\n]*)
    | (?P<num>\d+)
    | (?P<id>[A-Za-z_]\w*)
    | (?P<op>[-+*/()\[\],=])
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Token:
    kind: str
    value: object
    line: int


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    line = 1
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if match is None:
            raise ParseError(f"unexpected character {text[pos]!r} on line {line}")
        line += text[pos:match.end()].count("\n")
        pos = match.end()
        kind = match.lastgroup
        if kind in ("ws", "comment"):
            continue
        raw = match.group()
        value: object = int(raw) if kind == "num" else raw
        tokens.append(Token(kind, value, line))
    return tokens


def to_affine(expr: Expr, iv: str) -> Optional[Index]:
    """Reduce an index expression to ``coeff*iv + offset``, or ``None``."""
    if isinstance(expr, Num):
        return Index(0, expr.value)
    if isinstance(expr, Scalar):
        return Index(1, 0) if expr.name == iv else None
    if isinstance(expr, BinOp):
        left = to_affine(expr.left, iv)
        right = to_affine(expr.right, iv)
        if left is None or right is None:
            return None
        if expr.op == "+":
            return Index(left.coeff + right.coeff, left.offset + right.offset)
        if expr.op == "-":
            return Index(left.coeff - right.coeff, left.offset - right.offset)
        if expr.op == "*":
            if left.coeff == 0:
                return Index(right.coeff * left.offset, right.offset * left.offset)
            if right.coeff == 0:
                return Index(left.coeff * right.offset, left.offset * right.offset)
            return None
        if expr.op == "/":
            if right.coeff != 0 or right.offset == 0:
                return None
            if left.coeff % right.offset or left.offset % right.offset:
                return None
            return Index(left.coeff // right.offset, left.offset // right.offset)
    return None


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0
        self.iv = "i"

    # -- token helpers ------------------------------------------------------
    def _peek(self) -> Optional[Token]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _next(self) -> Token:
        token = self._peek()
        if token is None:
            raise ParseError("unexpected end of input")
        self.pos += 1
        return token

    def _expect_op(self, value: str) -> Token:
        token = self._peek()
        if token is None or token.kind != "op" or token.value != value:
            raise ParseError(f"expected {value!r} but found {self._describe(token)}")
        return self._next()

    def _expect_id(self) -> str:
        token = self._peek()
        if token is None or token.kind != "id":
            raise ParseError(f"expected an identifier but found {self._describe(token)}")
        self._next()
        return str(token.value)

    def _expect_num(self) -> int:
        token = self._peek()
        if token is None or token.kind != "num":
            raise ParseError(f"expected a number but found {self._describe(token)}")
        self._next()
        return int(token.value)  # type: ignore[arg-type]

    @staticmethod
    def _describe(token: Optional[Token]) -> str:
        return "end of input" if token is None else repr(token.value)

    # -- grammar ------------------------------------------------------------
    def parse_loop(self) -> Loop:
        vector_width = 4
        while True:
            token = self._peek()
            if token is None:
                raise ParseError("expected a 'loop <iv> = <start> to <end>' header")
            if token.kind == "id" and token.value == "vector_width":
                self._next()
                vector_width = self._expect_num()
                continue
            if token.kind == "id" and token.value == "loop":
                self._next()
                break
            raise ParseError(f"unexpected {self._describe(token)} before the loop header")

        self.iv = self._expect_id()
        self._expect_op("=")
        start = self._expect_num()
        keyword = self._expect_id()
        if keyword != "to":
            raise ParseError(f"expected 'to' in the loop header but found {keyword!r}")
        end = self._expect_num()

        statements: list[Statement] = []
        while True:
            token = self._peek()
            if token is None:
                raise ParseError("missing 'end' to close the loop")
            if token.kind == "id" and token.value == "end":
                self._next()
                break
            statements.append(self._parse_statement())

        return Loop(
            iv=self.iv,
            start=start,
            trip=end - start,
            statements=statements,
            vector_width=vector_width,
        )

    def _parse_statement(self) -> Statement:
        name = self._expect_id()
        self._expect_op("[")
        index_expr = self._parse_expr()
        self._expect_op("]")
        self._expect_op("=")
        value = self._parse_expr()
        index = to_affine(index_expr, self.iv)
        target = Ref(name, index=index, raw_index=None if index is not None else index_expr)
        return Statement(target, value)

    def _parse_expr(self) -> Expr:
        node = self._parse_term()
        while True:
            token = self._peek()
            if token is not None and token.kind == "op" and token.value in ("+", "-"):
                self._next()
                node = BinOp(str(token.value), node, self._parse_term())
            else:
                return node

    def _parse_term(self) -> Expr:
        node = self._parse_factor()
        while True:
            token = self._peek()
            if token is not None and token.kind == "op" and token.value in ("*", "/"):
                self._next()
                node = BinOp(str(token.value), node, self._parse_factor())
            else:
                return node

    def _parse_factor(self) -> Expr:
        token = self._peek()
        if token is None:
            raise ParseError("unexpected end of expression")
        if token.kind == "num":
            self._next()
            return Num(int(token.value))  # type: ignore[arg-type]
        if token.kind == "op" and token.value == "-":
            self._next()
            return BinOp("-", Num(0), self._parse_factor())
        if token.kind == "op" and token.value == "(":
            self._next()
            node = self._parse_expr()
            self._expect_op(")")
            return node
        if token.kind == "id":
            self._next()
            name = str(token.value)
            following = self._peek()
            if following is not None and following.kind == "op" and following.value == "[":
                self._next()
                index_expr = self._parse_expr()
                self._expect_op("]")
                index = to_affine(index_expr, self.iv)
                return Ref(name, index=index, raw_index=None if index is not None else index_expr)
            if following is not None and following.kind == "op" and following.value == "(":
                self._next()
                args: list[Expr] = []
                closing = self._peek()
                if not (closing is not None and closing.kind == "op" and closing.value == ")"):
                    args.append(self._parse_expr())
                    while True:
                        nxt = self._peek()
                        if nxt is not None and nxt.kind == "op" and nxt.value == ",":
                            self._next()
                            args.append(self._parse_expr())
                        else:
                            break
                self._expect_op(")")
                return Call(name, tuple(args))
            return Scalar(name)
        raise ParseError(f"unexpected {self._describe(token)} in expression")


def parse_text(text: str, source: str = "<text>") -> Loop:
    """Parse a string of toy IR into a :class:`~avlo.ir.Loop`."""
    loop = Parser(tokenize(text)).parse_loop()
    loop.source = source
    return loop


def parse_file(path: str | Path) -> Loop:
    """Parse a ``.loop`` file into a :class:`~avlo.ir.Loop`."""
    p = Path(path)
    return parse_text(p.read_text(encoding="utf-8"), source=str(p))
