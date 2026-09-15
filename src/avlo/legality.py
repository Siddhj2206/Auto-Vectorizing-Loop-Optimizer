"""Stage 4 - legality checker.

Verifies the project-specific preconditions before a loop is handed to the
transformer:

* every array index is affine in the induction variable;
* every array access is unit stride (``coeff == 1``), which is what the
  simple strip-mine transformer is able to emit correctly;
* only supported operators appear in the loop body;
* no unsupported construct (function call / exception / data-dependent
  branch) is present -- in this IR only calls are representable.

A loop that fails any precondition is left in scalar form.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .ir import SUPPORTED_BINOPS, Loop, render


@dataclass
class LegalityResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def check(loop: Loop) -> LegalityResult:
    reasons: list[str] = []

    for statement in loop.statements:
        if statement.target.index is None:
            reasons.append(f"non-affine write index: {render(statement.target, loop.iv)}")
        elif statement.target.index.coeff != 1:
            reasons.append(
                f"strided write access {render(statement.target, loop.iv)}; only "
                f"unit-stride accesses can be vectorized"
            )
        for ref in statement.reads():
            if ref.index is None:
                reasons.append(f"non-affine read index: {render(ref, loop.iv)}")
            elif ref.index.coeff != 1:
                reasons.append(
                    f"strided read access {render(ref, loop.iv)}; only "
                    f"unit-stride accesses can be vectorized"
                )
        for scalar in statement.value.scalars():
            if scalar.name == loop.iv:
                reasons.append(
                    f"induction variable {loop.iv!r} is used as a scalar value, "
                    f"which the vector transformer does not support"
                )
        for call in statement.calls():
            reasons.append(
                f"unsupported construct: function call {call.name}() in the loop body"
            )
        for op in statement.value.binops():
            if op not in SUPPORTED_BINOPS:
                reasons.append(f"unsupported operator {op!r} in the loop body")

    # De-duplicate messages while preserving discovery order.
    seen: set[str] = set()
    unique: list[str] = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            unique.append(reason)

    return LegalityResult(ok=not unique, reasons=unique)
