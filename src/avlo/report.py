"""Human-readable and JSON rendering of a pipeline :class:`~avlo.pipeline.Report`."""
from __future__ import annotations

from .pipeline import Report


def format_report(report: Report) -> str:
    loop = report.loop
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("Auto-Vectorizing Loop Optimizer")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Input ({loop.source}):")
    for line in loop.render().splitlines():
        lines.append(f"  {line}")
    lines.append("")

    lines.append(f"[1] Scope check         : {'PASS' if report.scope.ok else 'REJECT'}")
    for reason in report.scope.reasons:
        lines.append(f"      - {reason}")

    if report.dependence is not None:
        dep = report.dependence
        verdict = "LOOP-CARRIED DEPENDENCE" if dep.has_dependence else "INDEPENDENT"
        lines.append(f"[2] Dependence analysis : {verdict}")
        for item in dep.deps:
            lines.append(f"      - {item.kind} on {item.array}: {item.detail}")
        for note in dep.notes:
            lines.append(f"      note: {note}")
    else:
        lines.append("[2] Dependence analysis : not reached")

    if report.legality is not None:
        lines.append(f"[3] Legality check      : {'PASS' if report.legality.ok else 'REJECT'}")
        for reason in report.legality.reasons:
            lines.append(f"      - {reason}")
    else:
        lines.append("[3] Legality check      : not reached")

    lines.append("")
    lines.append(f"Verdict: {report.status}")
    lines.append(f"  {report.reason}")

    if report.transformed is not None:
        lines.append("")
        lines.append("Output IR:")
        for line in report.transformed.render().splitlines():
            lines.append(f"  {line}")
    return "\n".join(lines)


def to_dict(report: Report) -> dict:
    loop = report.loop
    out: dict = {
        "status": report.status,
        "vectorized": report.vectorized,
        "reason": report.reason,
        "loop": {
            "source": loop.source,
            "iv": loop.iv,
            "start": loop.start,
            "trip": loop.trip,
            "vector_width": loop.vector_width,
            "statements": [statement.render(loop.iv) for statement in loop.statements],
        },
        "scope": {"ok": report.scope.ok, "reasons": report.scope.reasons},
    }
    if report.dependence is not None:
        out["dependence"] = {
            "has_dependence": report.dependence.has_dependence,
            "notes": report.dependence.notes,
            "dependencies": [
                {
                    "array": item.array,
                    "kind": item.kind,
                    "distance": item.distance,
                    "detail": item.detail,
                }
                for item in report.dependence.deps
            ],
        }
    if report.legality is not None:
        out["legality"] = {"ok": report.legality.ok, "reasons": report.legality.reasons}
    if report.transformed is not None:
        transformed = report.transformed
        out["transform"] = {
            "vector_width": transformed.vector_width,
            "vector_trip": transformed.vector_trip,
            "remainder_trip": transformed.remainder_trip,
            "has_vector_loop": transformed.has_vector_loop,
            "has_remainder_loop": transformed.has_remainder_loop,
            "vector_body": [op.render(loop.iv) for op in transformed.vector_body],
        }
    return out
