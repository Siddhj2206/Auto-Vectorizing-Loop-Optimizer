"""Static operation counts for comparing scalar and vector pseudo-IR work.

These counts describe modeled operations only. They are not timings and do not
predict hardware speedup because AVLO emits and executes no machine SIMD.
"""
from __future__ import annotations

from .pipeline import Report


def operation_counts(report: Report) -> dict[str, int] | None:
    """Return dynamic modeled op counts for a vectorized loop, else ``None``."""
    if report.transformed is None:
        return None

    loop = report.loop
    transformed = report.transformed
    scalar_arithmetic_per_iteration = sum(
        len(statement.value.binops()) for statement in loop.statements
    )
    scalar_loads_per_iteration = sum(
        len(statement.reads()) for statement in loop.statements
    )
    scalar_stores_per_iteration = len(loop.statements)
    vector_iterations = transformed.vector_trip // transformed.vector_width
    vector_arithmetic_ops = sum(
        op.op in {"VADD", "VSUB", "VMUL", "VDIV", "VREM"}
        for op in transformed.vector_body
    )
    vector_load_ops = sum(op.op == "VLOAD" for op in transformed.vector_body)
    vector_store_ops = sum(op.op == "VSTORE" for op in transformed.vector_body)

    return {
        "scalar_arithmetic": scalar_arithmetic_per_iteration * loop.trip,
        "vector_arithmetic_lanes": (
            vector_arithmetic_ops * transformed.vector_trip
            + scalar_arithmetic_per_iteration * transformed.remainder_trip
        ),
        "vector_arithmetic_instructions": (
            vector_arithmetic_ops * vector_iterations
            + scalar_arithmetic_per_iteration * transformed.remainder_trip
        ),
        "scalar_loads": scalar_loads_per_iteration * loop.trip,
        "vector_load_instructions": (
            vector_load_ops * vector_iterations
            + scalar_loads_per_iteration * transformed.remainder_trip
        ),
        "scalar_stores": scalar_stores_per_iteration * loop.trip,
        "vector_store_instructions": (
            vector_store_ops * vector_iterations
            + scalar_stores_per_iteration * transformed.remainder_trip
        ),
        "vector_iterations": vector_iterations,
        "scalar_remainder_iterations": transformed.remainder_trip,
        "vector_width": transformed.vector_width,
    }


def format_trace(report: Report) -> str:
    """Render a concise execution trace of analysis and strip-mining decisions."""
    loop = report.loop
    lines = ["Execution trace:", f"  parsed {len(loop.statements)} statement(s), trip={loop.trip}"]
    lines.append(f"  scope: {'PASS' if report.scope.ok else 'REJECT'}")
    if report.dependence is None:
        lines.append("  dependence: not reached")
    else:
        lines.append(
            "  dependence: "
            + ("found " + str(len(report.dependence.deps)) + " dependence(s)"
               if report.dependence.has_dependence else "none found")
        )
        for dep in report.dependence.deps:
            lines.append(f"    {dep.kind} {dep.array}: {dep.detail}")
    if report.legality is None:
        lines.append("  legality: not reached")
    else:
        lines.append(f"  legality: {'PASS' if report.legality.ok else 'REJECT'}")
        lines.extend(f"    {reason}" for reason in report.legality.reasons)
    if report.transformed is not None:
        trans = report.transformed
        lines.append(
            f"  strip-mine: {trans.vector_trip} vectorized elements + "
            f"{trans.remainder_trip} scalar remainder (width {trans.vector_width})"
        )
        lines.append(f"  emitted pseudo-ops: {len(trans.vector_body)} per vector chunk")
    else:
        lines.append("  transform: skipped; original loop remains scalar")
    return "\n".join(lines)
