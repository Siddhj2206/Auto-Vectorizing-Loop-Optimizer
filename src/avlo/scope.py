"""Stage 2 - loop identification / scope check.

Confirms that the loop is a single-basic-block counted loop with a known,
non-negative trip count and a body that this IR is able to represent. The
text format cannot express control flow, so the structural assumptions are
mostly enforced by the parser; this stage is the explicit gate that keeps
anything outside the supported shape from reaching the analyses.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .ir import Loop


@dataclass
class ScopeResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def check(loop: Loop) -> ScopeResult:
    reasons: list[str] = []

    if loop.trip < 0:
        reasons.append(
            f"trip count is negative ({loop.trip}); only counted loops with a "
            f"known non-negative trip count are in scope"
        )
    if not loop.statements and loop.trip > 0:
        reasons.append("loop body is empty; expected at least one statement")
    for statement in loop.statements:
        if statement.target.array == loop.iv:
            reasons.append(
                f"the induction variable {loop.iv!r} is used as an array name"
            )
        if statement.target.index is None:
            reasons.append(
                f"array index could not be reduced to an affine form for "
                f"{statement.target.array}[...]"
            )

    return ScopeResult(ok=not reasons, reasons=reasons)
