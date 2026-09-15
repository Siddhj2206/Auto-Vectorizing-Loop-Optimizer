"""Stage 5 - vectorizing transformer.

Performs loop strip-mining with a configurable vector width ``V``:

* the trip count is split into ``vector_trip = (trip // V) * V`` iterations
  handled by a vector main loop, plus ``remainder_trip = trip % V`` leftover
  iterations handled by a scalar remainder loop;
* the vector main loop body is the scalar body lowered into VLOAD / VBCAST /
  VADD / VSUB / VMUL / VDIV / VSTORE pseudo-operations.

Requires the loop to be legal and dependency-free; the pipeline enforces that
ordering before calling in.
"""
from __future__ import annotations

from .ir import BinOp, Call, Loop, Num, Operand, Ref, Scalar, Transformed, VectorOp

_VECTOR_OP = {"+": "VADD", "-": "VSUB", "*": "VMUL", "/": "VDIV"}


class _Temps:
    def __init__(self) -> None:
        self.count = 0

    def new(self) -> str:
        name = f"v{self.count}"
        self.count += 1
        return name


def transform(loop: Loop) -> Transformed:
    width = loop.vector_width
    vector_trip = (loop.trip // width) * width
    remainder_trip = loop.trip - vector_trip
    return Transformed(
        loop=loop,
        vector_width=width,
        vector_trip=vector_trip,
        remainder_trip=remainder_trip,
        vector_body=_vectorize(loop),
    )


def _vectorize(loop: Loop) -> list[VectorOp]:
    ops: list[VectorOp] = []
    temps = _Temps()
    for statement in loop.statements:
        value = _lower(statement.value, ops, temps)
        ops.append(
            VectorOp(
                "VSTORE",
                (
                    Operand("mem", name=statement.target.array, index=statement.target.index),
                    value,
                ),
            )
        )
    return ops


def _lower(expr, ops: list[VectorOp], temps: _Temps) -> Operand:
    if isinstance(expr, Num):
        return Operand("num", value=expr.value)
    if isinstance(expr, Scalar):
        dest = temps.new()
        ops.append(VectorOp("VBCAST", (Operand("scalar", name=expr.name),), dest=dest))
        return Operand("temp", name=dest)
    if isinstance(expr, Ref):
        dest = temps.new()
        ops.append(
            VectorOp("VLOAD", (Operand("mem", name=expr.array, index=expr.index),), dest=dest)
        )
        return Operand("temp", name=dest)
    if isinstance(expr, BinOp):
        left = _lower(expr.left, ops, temps)
        right = _lower(expr.right, ops, temps)
        dest = temps.new()
        ops.append(VectorOp(_VECTOR_OP[expr.op], (left, right), dest=dest))
        return Operand("temp", name=dest)
    if isinstance(expr, Call):
        raise ValueError(f"cannot vectorize a call to {expr.name}()")
    raise TypeError(f"cannot vectorize expression {expr!r}")
