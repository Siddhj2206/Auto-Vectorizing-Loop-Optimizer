"""Stage 3 - loop-carried dependence analysis.

A simplified GCD / Banerjee-style offset comparison. For every pair of
accesses to the same array (with at least one write) we ask whether the two
accesses can touch the same element in *different* iterations:

* equal coefficients ``c1 == c1'`` give an exact dependence distance
  ``d = (offset' - offset) / c1``, and the pair is loop-carried when
  ``0 < |d| < trip``;
* differing coefficients fall back to the GCD necessary condition --
  if ``gcd(c1, c1')`` does not divide the offset difference the accesses are
  independent, otherwise the simplified test cannot prove independence and
  the pair is treated conservatively as possibly dependent.

Read-read pairs are skipped (they commute), and accesses to different arrays
are assumed not to alias -- a stated assumption of the project scope.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .ir import Index, Loop, Statement, render

READ = "read"
WRITE = "write"


@dataclass(frozen=True)
class Access:
    array: str
    index: Index
    role: str
    statement: Statement
    rendered: str


@dataclass
class Dependence:
    array: str
    kind: str
    distance: Optional[int]
    first: Access
    second: Access
    detail: str


@dataclass
class DependenceResult:
    has_dependence: bool
    deps: list[Dependence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def collect_accesses(loop: Loop) -> list[Access]:
    accesses: list[Access] = []
    for statement in loop.statements:
        target = statement.target
        if target.index is not None:
            accesses.append(
                Access(target.array, target.index, WRITE, statement, render(target, loop.iv))
            )
        for ref in statement.reads():
            if ref.index is not None:
                accesses.append(
                    Access(ref.array, ref.index, READ, statement, render(ref, loop.iv))
                )
    return accesses


def _kind(first: Access, second: Access, distance: Optional[int]) -> str:
    if first.role == WRITE and second.role == WRITE:
        return "WAW"
    if distance is None:
        return "RAW/WAR"
    write_first = (first.role == WRITE and distance < 0) or (
        second.role == WRITE and distance > 0
    )
    return "RAW" if write_first else "WAR"


def _pair(first: Access, second: Access, trip: int) -> Optional[Dependence]:
    if trip <= 0:
        return None
    a, b = first.index, second.index

    if a.coeff == b.coeff:
        if a.offset == b.offset:
            # Same location, but only when both accesses are in the *same*
            # iteration, so there is no loop-carried dependence.
            return None
        if a.coeff == 0:
            # Two distinct constant indices never coincide.
            return None
        delta = b.offset - a.offset
        if delta % a.coeff != 0:
            return None
        distance = delta // a.coeff
        if distance == 0 or abs(distance) >= trip:
            return None
        return Dependence(
            first.array,
            _kind(first, second, distance),
            distance,
            first,
            second,
            f"{first.rendered} ({first.role}) and {second.rendered} ({second.role}) "
            f"can reference the same element at a distance of {distance} iteration(s)",
        )

    g = math.gcd(abs(a.coeff), abs(b.coeff))
    if (b.offset - a.offset) % g != 0:
        return None
    return Dependence(
        first.array,
        _kind(first, second, None),
        None,
        first,
        second,
        f"{first.rendered} ({first.role}) and {second.rendered} ({second.role}) "
        f"have coefficient gcd {g}, which admits a solution; the simplified test "
        f"cannot prove independence, so the pair is treated as possibly dependent",
    )


def analyze(loop: Loop) -> DependenceResult:
    accesses = collect_accesses(loop)
    result = DependenceResult(has_dependence=False)

    # Offset-based comparison assumes distinct arrays do not alias.
    arrays = {access.array for access in accesses}
    if len(arrays) > 1:
        result.notes.append(
            "distinct arrays are assumed not to alias (stated project assumption)"
        )

    for i in range(len(accesses)):
        for j in range(i + 1, len(accesses)):
            first, second = accesses[i], accesses[j]
            if first.array != second.array:
                continue
            if first.role == READ and second.role == READ:
                continue
            dep = _pair(first, second, loop.trip)
            if dep is not None:
                result.deps.append(dep)

    result.has_dependence = bool(result.deps)
    return result
