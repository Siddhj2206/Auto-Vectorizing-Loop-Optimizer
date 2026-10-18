"""Command-line entry point: ``avlo <file.loop>``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .executor import verify
from .c_frontend import parse_c_file
from .metrics import format_trace, operation_counts
from .parser import ParseError, parse_file
from .pipeline import analyze
from .report import format_report, to_dict


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="avlo",
        description=(
            "Auto-Vectorizing Loop Optimizer: analyze C source or toy IR and "
            "annotate supported C loops for SIMD compilation."
        ),
    )
    parser.add_argument(
        "loop_file",
        type=Path,
        help="path to a .c source file or a .loop toy-IR file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the analysis report as JSON instead of text",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "execute the original scalar loop and the transformed loop on identical "
            "inputs and check that they produce the same arrays (toy IR only)"
        ),
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="show stage decisions and the strip-mining iteration split",
    )
    parser.add_argument(
        "--metrics",
        action="store_true",
        help="show modeled scalar and vector pseudo-operation counts (not timings)",
    )
    parser.add_argument(
        "--emit-c",
        type=Path,
        metavar="OUTPUT.c",
        help="for C input, write source with #pragma omp simd on proven-safe loops",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.loop_file.suffix.lower() == ".c":
        return _main_c(args)
    if args.emit_c:
        print("error: --emit-c requires a .c input file", file=sys.stderr)
        return 2

    try:
        loop = parse_file(args.loop_file)
    except FileNotFoundError:
        print(f"error: file not found: {args.loop_file}", file=sys.stderr)
        return 2
    except ParseError as exc:
        print(f"parse error in {args.loop_file}: {exc}", file=sys.stderr)
        return 2

    report = analyze(loop)
    if args.json:
        print(json.dumps(to_dict(report), indent=2))
    else:
        print(format_report(report))

    if args.trace:
        print("\n" + format_trace(report))

    if args.metrics:
        counts = operation_counts(report)
        if counts is None:
            print("\nOperation counts: unavailable (loop was not vectorized)")
        else:
            print("\nModeled operation counts (not measured performance):")
            print(f"  scalar arithmetic operations: {counts['scalar_arithmetic']}")
            print(
                "  vector arithmetic lane operations: "
                f"{counts['vector_arithmetic_lanes']}"
            )
            print(
                "  vector arithmetic pseudo-instructions: "
                f"{counts['vector_arithmetic_instructions']}"
            )
            print(
                f"  loads: {counts['scalar_loads']} scalar element reads vs "
                f"{counts['vector_load_instructions']} vector/scalar load instructions"
            )
            print(
                f"  stores: {counts['scalar_stores']} scalar element writes vs "
                f"{counts['vector_store_instructions']} vector/scalar store instructions"
            )
            print(
                f"  chunks: {counts['vector_iterations']} at width "
                f"{counts['vector_width']}; scalar tail: "
                f"{counts['scalar_remainder_iterations']} iteration(s)"
            )

    if args.verify:
        if not report.vectorized:
            print("\nEquivalence check: skipped (loop was not vectorized)")
            return 0
        result = verify(loop)
        print(f"\nEquivalence check: {'PASS' if result.equal else 'FAIL'}")
        for name, index, scalar, vector in result.mismatches:
            print(f"  mismatch {name}[{index}]: scalar={scalar} vectorized={vector}")
        return 0 if result.equal else 1

    return 0


def _main_c(args) -> int:
    try:
        candidates = parse_c_file(args.loop_file)
    except FileNotFoundError:
        print(f"error: file not found: {args.loop_file}", file=sys.stderr)
        return 2
    except ParseError as exc:
        print(f"C parse error in {args.loop_file}: {exc}", file=sys.stderr)
        return 2

    if not candidates:
        print(f"No for-loops found in {args.loop_file}")
        return 0

    entries = []
    analyzed_reports = []
    for candidate in candidates:
        if candidate.loop is None:
            entries.append({"line": candidate.line, "status": "UNSUPPORTED", "reason": candidate.reason})
            analyzed_reports.append(None)
            continue
        report = analyze(candidate.loop)
        # The custom IR needs a concrete trip count. The source C retains its
        # runtime bound, and the large internal bound is only used to be
        # conservative in dependence-distance checks.
        if candidate.dynamic_trip:
            report.transformed = None
        entries.append({
            "line": candidate.line,
            "status": report.status,
            "reason": report.reason,
            "dynamic_bound": candidate.dynamic_trip,
            "dependence": None if report.dependence is None else {
                "has_dependence": report.dependence.has_dependence,
                "dependencies": [dep.detail for dep in report.dependence.deps],
            },
            "legality": None if report.legality is None else {
                "ok": report.legality.ok, "reasons": report.legality.reasons,
            },
        })
        analyzed_reports.append(report)

    if args.emit_c:
        source_text = args.loop_file.read_text(encoding="utf-8")
        insertions: list[tuple[int, str]] = []
        for candidate, entry in zip(candidates, entries):
            if entry.get("status") != "VECTORIZED":
                continue
            reductions = candidate.reductions or []
            clauses = " ".join(f"reduction({op}:{name})" for name, op in reductions)
            suffix = f" {clauses}" if clauses else ""
            insertions.append((
                _source_offset(source_text, candidate.line, candidate.column),
                f"#pragma omp simd{suffix}",
            ))
            for _, function_line, function_column in candidate.declare_simd or []:
                insertions.append((
                    _source_offset(source_text, function_line, function_column),
                    "#pragma omp declare simd",
                ))
        for offset, insertion in sorted(insertions, key=lambda item: item[0], reverse=True):
            source_text = _insert_directive(source_text, offset, insertion)
        args.emit_c.write_text(source_text, encoding="utf-8")

    if args.json:
        print(json.dumps({"source": str(args.loop_file), "loops": entries}, indent=2))
        if args.emit_c:
            print(f"Wrote annotated C source: {args.emit_c}")
        return 0

    for candidate, entry, report in zip(candidates, entries, analyzed_reports):
        print(f"C loop at {args.loop_file}:{entry['line']}")
        if entry.get("status") == "UNSUPPORTED":
            print(f"  Unsupported: {entry['reason']}\n")
            continue
        print(f"  Scope: {'PASS' if report.scope.ok else 'REJECT'}")
        if report.dependence is None:
            print("  Dependence: not reached")
        elif report.dependence.has_dependence:
            print("  Dependence: found")
            for dep in report.dependence.deps:
                print(f"    {dep.kind}: {dep.detail}")
        else:
            print("  Dependence: none found")
        if report.legality is None:
            print("  Legality: not reached")
        else:
            print(f"  Legality: {'PASS' if report.legality.ok else 'REJECT'}")
            for reason in report.legality.reasons:
                print(f"    {reason}")
        print(f"  Result: {report.status} — {report.reason}")
        if candidate.dynamic_trip:
            print("  Bound: runtime scalar (dependence test uses a conservative trip estimate)")
        if args.trace:
            print("\nTrace: C source loop passed through scope, dependence and legality checks")
            if candidate.dynamic_trip:
                print("  runtime bound retained; dependence analysis used a conservative trip estimate")
            if report.vectorized:
                print("  loop source is preserved; --emit-c adds the SIMD directive")
            else:
                print("  source loop remains unchanged")
        if args.metrics:
            counts = None if candidate.dynamic_trip or candidate.reductions else operation_counts(report)
            if counts is None:
                print("\nOperation counts: unavailable for source-level C analysis")
            else:
                print("\nModeled operation counts (not measured performance):")
                print(f"  scalar arithmetic operations: {counts['scalar_arithmetic']}")
                print(f"  vector arithmetic lane operations: {counts['vector_arithmetic_lanes']}")
                print(f"  vector arithmetic pseudo-instructions: {counts['vector_arithmetic_instructions']}")
                print(f"  vector chunks: {counts['vector_iterations']}; scalar tail: {counts['scalar_remainder_iterations']}")
        if args.verify:
            print("\nC equivalence check: not available; --verify executes only the toy-IR model")
        print()
    if args.emit_c:
        print(f"Wrote annotated C source: {args.emit_c}")
    return 0


def _source_offset(source: str, line: int, column: int) -> int:
    """Convert a one-based source line/column to a character offset."""
    if line < 1:
        return 0
    offset = 0
    for current, text in enumerate(source.splitlines(keepends=True), start=1):
        if current == line:
            return offset + min(max(column - 1, 0), len(text.rstrip("\r\n")))
        offset += len(text)
    return len(source)


def _insert_directive(source: str, offset: int, directive: str) -> str:
    """Split a source line at a loop/function token and insert a C pragma."""
    line_start = source.rfind("\n", 0, offset) + 1
    prefix = source[line_start:offset]
    leading = prefix[:len(prefix) - len(prefix.lstrip())]
    if not prefix.strip():
        return source[:line_start] + f"{leading}{directive}\n" + source[line_start:]
    return (
        source[:offset]
        + f"\n{leading}{directive}\n{leading}"
        + source[offset:]
    )


if __name__ == "__main__":
    raise SystemExit(main())
