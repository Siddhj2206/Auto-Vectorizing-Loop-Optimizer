"""Toy-IR interpreter and equivalence checker.

Executes the original scalar loop and the strip-mined output over identical
arrays and compares the results. This turns the project's correctness
condition -- "the vectorized output must compute the same array values as the
original scalar loop" -- into an executable check rather than a claim.

The vector main loop is executed by interpreting the emitted pseudo-ops:
``VLOAD`` reads ``V`` consecutive elements, ``VBCAST`` broadcasts a scalar, the
arithmetic ops run element-wise, and ``VSTORE`` writes ``V`` consecutive
elements. If strip-mining failed to partition the iteration space exactly, the
comparison fails.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Optional

from .ir import BinOp, Call, Expr, Loop, Num, Operand, Ref, Scalar, Transformed
from .transform import transform


class ExecutionError(Exception):
    """Raised when a loop cannot be executed (unsupported construct)."""


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def _default_value(array: str, index: int) -> float:
    seed = sum(ord(c) for c in array)
    return float((seed + index) % 19) + 1.0


def default_scalars(loop: Loop) -> dict[str, float]:
    names: list[str] = []
    for statement in loop.statements:
        for scalar in statement.value.scalars():
            if scalar.name != loop.iv and scalar.name not in names:
                names.append(scalar.name)
    return {name: 2.0 + position for position, name in enumerate(names)}


def make_arrays(loop: Loop) -> dict[str, dict[int, float]]:
    """Deterministic starting values covering every index the loop touches."""
    spans: dict[str, list[int]] = {}
    for statement in loop.statements:
        for ref in [statement.target, *statement.reads()]:
            if ref.index is None:
                continue
            if ref.index.coeff == 0:
                lo = hi = ref.index.offset
            else:
                values = [
                    ref.index.coeff * i + ref.index.offset
                    for i in range(loop.start, loop.end)
                ]
                if not values:
                    continue
                lo, hi = min(values), max(values)
            span = spans.setdefault(ref.array, [lo, hi])
            span[0] = min(span[0], lo)
            span[1] = max(span[1], hi)
    return {
        name: {k: _default_value(name, k) for k in range(lo, hi + 1)}
        for name, (lo, hi) in spans.items()
    }


# ---------------------------------------------------------------------------
# Scalar execution
# ---------------------------------------------------------------------------
def _eval(expr: Expr, arrays, scalars, i: int):
    if isinstance(expr, Num):
        return expr.value
    if isinstance(expr, Scalar):
        if expr.name not in scalars:
            raise ExecutionError(f"unknown scalar {expr.name!r}")
        return scalars[expr.name]
    if isinstance(expr, Ref):
        index = expr.index.coeff * i + expr.index.offset
        return arrays[expr.array][index]
    if isinstance(expr, BinOp):
        left = _eval(expr.left, arrays, scalars, i)
        right = _eval(expr.right, arrays, scalars, i)
        if expr.op == "+":
            return left + right
        if expr.op == "-":
            return left - right
        if expr.op == "*":
            return left * right
        if expr.op == "/":
            return left / right
        raise ExecutionError(f"unsupported operator {expr.op!r}")
    if isinstance(expr, Call):
        raise ExecutionError(f"cannot execute call {expr.name}()")
    raise ExecutionError(f"cannot execute {expr!r}")


def _store(statement, arrays, scalars, i: int) -> None:
    index = statement.target.index.coeff * i + statement.target.index.offset
    arrays[statement.target.array][index] = _eval(statement.value, arrays, scalars, i)


def run_scalar(loop: Loop, arrays, scalars) -> None:
    for i in range(loop.start, loop.end):
        for statement in loop.statements:
            _store(statement, arrays, scalars, i)


# ---------------------------------------------------------------------------
# Vectorized execution
# ---------------------------------------------------------------------------
def _resolve(operand: Operand, temps, scalars, width: int) -> list:
    if operand.kind == "temp":
        return temps[operand.name]
    if operand.kind == "num":
        return [operand.value] * width
    if operand.kind == "scalar":
        return [scalars[operand.name]] * width
    raise ExecutionError(f"cannot resolve operand {operand!r}")


def _run_vector_body(transformed: Transformed, arrays, scalars, i: int) -> None:
    width = transformed.vector_width
    temps: dict[str, list] = {}
    for op in transformed.vector_body:
        if op.op == "VBCAST":
            temps[op.dest] = [scalars[op.operands[0].name]] * width
        elif op.op == "VLOAD":
            operand = op.operands[0]
            base = operand.index.coeff * i + operand.index.offset
            temps[op.dest] = [arrays[operand.name][base + k] for k in range(width)]
        elif op.op in ("VADD", "VSUB", "VMUL", "VDIV"):
            left = _resolve(op.operands[0], temps, scalars, width)
            right = _resolve(op.operands[1], temps, scalars, width)
            if op.op == "VADD":
                temps[op.dest] = [a + b for a, b in zip(left, right)]
            elif op.op == "VSUB":
                temps[op.dest] = [a - b for a, b in zip(left, right)]
            elif op.op == "VMUL":
                temps[op.dest] = [a * b for a, b in zip(left, right)]
            else:
                temps[op.dest] = [a / b for a, b in zip(left, right)]
        elif op.op == "VSTORE":
            mem, value = op.operands
            base = mem.index.coeff * i + mem.index.offset
            vector = _resolve(value, temps, scalars, width)
            for k in range(width):
                arrays[mem.name][base + k] = vector[k]
        else:
            raise ExecutionError(f"unknown vector op {op.op!r}")


def run_vectorized(transformed: Transformed, arrays, scalars) -> None:
    loop = transformed.loop
    width = transformed.vector_width
    if transformed.has_vector_loop:
        for i in range(loop.start, loop.start + transformed.vector_trip, width):
            _run_vector_body(transformed, arrays, scalars, i)
    for i in range(loop.start + transformed.vector_trip, loop.end):
        for statement in loop.statements:
            _store(statement, arrays, scalars, i)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
@dataclass
class VerificationResult:
    equal: bool
    scalar: dict
    vectorized: dict

    @property
    def mismatches(self) -> list[tuple[str, int, object, object]]:
        out: list[tuple[str, int, object, object]] = []
        for name in sorted(set(self.scalar) | set(self.vectorized)):
            scalar = self.scalar.get(name, {})
            vector = self.vectorized.get(name, {})
            for index in sorted(set(scalar) | set(vector)):
                if scalar.get(index) != vector.get(index):
                    out.append((name, index, scalar.get(index), vector.get(index)))
        return out


def verify(loop: Loop, scalars: Optional[dict] = None) -> VerificationResult:
    """Run the scalar loop and its strip-mined form on identical inputs."""
    scalars = dict(scalars) if scalars is not None else default_scalars(loop)
    base = make_arrays(loop)
    transformed = transform(loop)
    scalar_arrays = copy.deepcopy(base)
    vector_arrays = copy.deepcopy(base)
    run_scalar(loop, scalar_arrays, scalars)
    run_vectorized(transformed, vector_arrays, scalars)
    return VerificationResult(
        equal=scalar_arrays == vector_arrays,
        scalar=scalar_arrays,
        vectorized=vector_arrays,
    )
