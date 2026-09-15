"""Toy IR data model.

The IR is deliberately minimal: a single counted loop over a single
induction variable, a straight-line sequence of assignment statements,
and array references whose indices are affine in the induction variable.
It carries exactly what the later stages need and nothing more.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: Binary operators the toy IR understands.
SUPPORTED_BINOPS = {"+", "-", "*", "/"}

#: Precedence used by :func:`render` so printed expressions stay readable.
_PRECEDENCE = {"+": 1, "-": 1, "*": 2, "/": 2}


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Index:
    """An affine access index ``coeff * iv + offset``."""

    coeff: int
    offset: int

    def render(self, iv: str = "i") -> str:
        if self.coeff == 0:
            return str(self.offset)
        if self.coeff == 1:
            body = iv
        elif self.coeff == -1:
            body = f"-{iv}"
        else:
            body = f"{self.coeff}*{iv}"
        if self.offset > 0:
            return f"{body}+{self.offset}"
        if self.offset < 0:
            return f"{body}-{abs(self.offset)}"
        return body


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------
class Expr:
    """Base class for IR expressions."""

    def reads(self) -> list["Ref"]:
        return []

    def calls(self) -> list["Call"]:
        return []

    def binops(self) -> list[str]:
        return []

    def scalars(self) -> list["Scalar"]:
        return []


@dataclass(frozen=True)
class Num(Expr):
    """An integer literal."""

    value: int


@dataclass(frozen=True)
class Scalar(Expr):
    """A loop-invariant scalar variable (for example the ``alpha`` in SAXPY)."""

    name: str

    def scalars(self) -> list["Scalar"]:
        return [self]


@dataclass(frozen=True)
class Ref(Expr):
    """An array reference.

    ``index`` is ``None`` when the access index is not affine; the raw
    expression is kept in ``raw_index`` so the legality checker can report
    exactly what it rejected.
    """

    array: str
    index: Optional[Index] = None
    raw_index: Optional[Expr] = None

    def reads(self) -> list["Ref"]:
        return [self]


@dataclass(frozen=True)
class BinOp(Expr):
    op: str
    left: Expr
    right: Expr

    def reads(self) -> list["Ref"]:
        return self.left.reads() + self.right.reads()

    def calls(self) -> list["Call"]:
        return self.left.calls() + self.right.calls()

    def binops(self) -> list[str]:
        return [self.op] + self.left.binops() + self.right.binops()

    def scalars(self) -> list["Scalar"]:
        return self.left.scalars() + self.right.scalars()


@dataclass(frozen=True)
class Call(Expr):
    """A function call. Out of scope for the vectorizer, but representable so
    the legality checker can reject the loop with a precise reason."""

    name: str
    args: tuple[Expr, ...] = ()

    def reads(self) -> list["Ref"]:
        out: list[Ref] = []
        for arg in self.args:
            out.extend(arg.reads())
        return out

    def calls(self) -> list["Call"]:
        out = [self]
        for arg in self.args:
            out.extend(arg.calls())
        return out

    def binops(self) -> list[str]:
        out: list[str] = []
        for arg in self.args:
            out.extend(arg.binops())
        return out

    def scalars(self) -> list["Scalar"]:
        out: list[Scalar] = []
        for arg in self.args:
            out.extend(arg.scalars())
        return out


def render(e: Expr, iv: str = "i", min_precedence: int = 0) -> str:
    """Render an expression back to readable toy-IR text."""
    if isinstance(e, Num):
        return str(e.value)
    if isinstance(e, Scalar):
        return e.name
    if isinstance(e, Ref):
        if e.index is not None:
            idx = e.index.render(iv)
        elif e.raw_index is not None:
            idx = render(e.raw_index, iv)
        else:
            idx = "?"
        return f"{e.array}[{idx}]"
    if isinstance(e, Call):
        return f"{e.name}({', '.join(render(a, iv) for a in e.args)})"
    if isinstance(e, BinOp):
        precedence = _PRECEDENCE[e.op]
        left = render(e.left, iv, precedence)
        right = render(e.right, iv, precedence + 1)
        text = f"{left} {e.op} {right}"
        if precedence < min_precedence:
            return f"({text})"
        return text
    return repr(e)


# ---------------------------------------------------------------------------
# Statements and loops
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Statement:
    """A single assignment ``target = value``."""

    target: Ref
    value: Expr

    def reads(self) -> list[Ref]:
        return self.value.reads()

    def calls(self) -> list[Call]:
        return self.value.calls()

    def render(self, iv: str = "i") -> str:
        return f"{render(self.target, iv)} = {render(self.value, iv)}"


@dataclass
class Loop:
    """A single-basic-block counted loop in the toy IR."""

    iv: str
    start: int
    trip: int
    statements: list[Statement] = field(default_factory=list)
    vector_width: int = 4
    source: str = "<memory>"

    @property
    def end(self) -> int:
        """Exclusive upper bound of the induction variable."""
        return self.start + self.trip

    def arrays(self) -> list[str]:
        seen: list[str] = []
        for statement in self.statements:
            for ref in [statement.target, *statement.reads()]:
                if ref.array not in seen:
                    seen.append(ref.array)
        return seen

    def render(self) -> str:
        lines = [
            f"loop {self.iv} = {self.start} to {self.end}"
            f"    (trip count = {self.trip}, vector width = {self.vector_width})"
        ]
        for statement in self.statements:
            lines.append(f"    {statement.render(self.iv)}")
        lines.append("end")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Vectorized output
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Operand:
    """A vector operand: a temp, an array access, a scalar or a literal."""

    kind: str  # "temp" | "mem" | "scalar" | "num"
    name: str = ""
    index: Optional[Index] = None
    value: int = 0

    def render(self, iv: str = "i") -> str:
        if self.kind == "temp":
            return self.name
        if self.kind == "mem":
            idx = self.index.render(iv) if self.index is not None else "?"
            return f"{self.name}[{idx}]"
        if self.kind == "scalar":
            return self.name
        if self.kind == "num":
            return str(self.value)
        return "?"


@dataclass(frozen=True)
class VectorOp:
    """A pseudo vector operation in the emitted output IR."""

    op: str
    operands: tuple[Operand, ...]
    dest: Optional[str] = None

    def render(self, iv: str = "i") -> str:
        args = ", ".join(operand.render(iv) for operand in self.operands)
        if self.dest is None:
            return f"{self.op} {args}"
        return f"{self.dest} = {self.op} {args}"


@dataclass
class Transformed:
    """The result of strip-mining a legal, dependency-free loop."""

    loop: Loop
    vector_width: int
    vector_trip: int
    remainder_trip: int
    vector_body: list[VectorOp] = field(default_factory=list)

    @property
    def has_vector_loop(self) -> bool:
        return self.vector_trip > 0

    @property
    def has_remainder_loop(self) -> bool:
        return self.remainder_trip > 0

    def render(self) -> str:
        out: list[str] = []
        start = self.loop.start
        iv = self.loop.iv

        if self.has_vector_loop:
            hi = start + self.vector_trip
            step = self.vector_width
            out.append(
                f"# vector main loop: {iv} = {start}, {start + step}, ... < {hi}"
                f"  ({self.vector_trip // step} vector iteration(s) of width {step})"
            )
            out.append(f"{iv} = {start}")
            out.append(f"while {iv} < {hi}:")
            for op in self.vector_body:
                out.append(f"    {op.render(iv)}")
            out.append(f"    {iv} = {iv} + {step}")

        if self.has_remainder_loop:
            rlo = start + self.vector_trip
            rhi = rlo + self.remainder_trip
            out.append(
                f"# scalar remainder loop: {iv} = {rlo} .. < {rhi}"
                f"  ({self.remainder_trip} iteration(s))"
            )
            out.append(f"{iv} = {rlo}")
            out.append(f"while {iv} < {rhi}:")
            for statement in self.loop.statements:
                out.append(f"    {statement.render(iv)}")
            out.append(f"    {iv} = {iv} + 1")

        if not self.has_vector_loop and not self.has_remainder_loop:
            out.append("# trip count is 0: nothing to emit")
        return "\n".join(out)
