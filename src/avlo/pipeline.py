"""End-to-end driver.

Pipeline order (matching the approved Review 1 architecture)::

    scope check -> dependence analysis -> legality check -> transform

Each stage can reject the loop and leave it in scalar form; the first
rejection wins and the later stages are not run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import dependence, legality, scope, transform
from .dependence import DependenceResult
from .ir import Loop, Transformed
from .legality import LegalityResult
from .scope import ScopeResult

VECTORIZED = "VECTORIZED"
REJECTED = "REJECTED (kept scalar)"


@dataclass
class Report:
    loop: Loop
    scope: ScopeResult
    dependence: Optional[DependenceResult] = None
    legality: Optional[LegalityResult] = None
    transformed: Optional[Transformed] = None
    status: str = REJECTED
    reason: str = ""

    @property
    def vectorized(self) -> bool:
        return self.status == VECTORIZED


def analyze(loop: Loop) -> Report:
    scope_result = scope.check(loop)
    if not scope_result.ok:
        return Report(
            loop, scope_result, status=REJECTED,
            reason="scope: " + "; ".join(scope_result.reasons),
        )

    dependence_result = dependence.analyze(loop)
    if dependence_result.has_dependence:
        return Report(
            loop, scope_result, dependence=dependence_result, status=REJECTED,
            reason="loop-carried dependence: "
            + "; ".join(dep.detail for dep in dependence_result.deps),
        )

    legality_result = legality.check(loop)
    if not legality_result.ok:
        return Report(
            loop, scope_result, dependence=dependence_result,
            legality=legality_result, status=REJECTED,
            reason="legality: " + "; ".join(legality_result.reasons),
        )

    transformed = transform.transform(loop)
    return Report(
        loop, scope_result, dependence=dependence_result,
        legality=legality_result, transformed=transformed, status=VECTORIZED,
        reason="loop is dependency-free and satisfies all legality preconditions",
    )
