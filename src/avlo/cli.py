"""Command-line entry point: ``avlo <file.loop>``."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .executor import verify
from .c_frontend import parse_c_file
from .metrics import format_trace, operation_counts
from .parser import ParseError, parse_file
from .pipeline import analyze
from .report import format_report, to_dict
from .c_transform import transformed_source


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
    parser.add_argument(
        "--width",
        type=int,
        metavar="N",
        help="lane count for the printed strip-mined code (overrides #pragma avlo width)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.width is not None and args.width < 1:
        print("error: --width must be at least 1", file=sys.stderr)
        return 2

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

    if args.width is not None:
        loop.vector_width = args.width
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
            print("\nModeled operations (not timings):")
            print(
                f"  arithmetic: {counts['scalar_arithmetic']} scalar -> "
                f"{counts['vector_arithmetic_instructions']} instructions "
                f"({counts['vector_arithmetic_lanes']} lanes)"
            )
            print(
                f"  loads: {counts['scalar_loads']} -> "
                f"{counts['vector_load_instructions']} instructions"
            )
            print(
                f"  stores: {counts['scalar_stores']} -> "
                f"{counts['vector_store_instructions']} instructions"
            )
            print(
                f"  chunks: {counts['vector_iterations']} x {counts['vector_width']}, "
                f"tail {counts['scalar_remainder_iterations']}"
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
        source_text = args.loop_file.read_text(encoding="utf-8")
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

    display_width = args.width if args.width is not None else _declared_width(source_text) or 4

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

    annotated_source = _annotated_source(args.loop_file, candidates, entries)
    if args.emit_c:
        args.emit_c.write_text(annotated_source, encoding="utf-8")

    if args.json:
        print(json.dumps({"source": str(args.loop_file), "loops": entries}, indent=2))
        if args.emit_c:
            print(f"Wrote {args.emit_c}")
        return 0

    for candidate, entry, report in zip(candidates, entries, analyzed_reports):
        location = f"{args.loop_file}:{entry['line']}"
        if entry.get("status") == "UNSUPPORTED":
            print(f"{location}  UNSUPPORTED ({entry['reason']})")
            continue
        stage = (
            "scope PASS" if report.scope.ok
            else "scope REJECT (" + "; ".join(report.scope.reasons) + ")"
        )
        if report.dependence is None:
            dependence = "dependence not reached"
        elif report.dependence.deps:
            dependence = "dependence " + "; ".join(
                _dependence_text(dep) for dep in report.dependence.deps
            )
        else:
            dependence = "dependence none"
        if report.legality is None:
            legality = "legality not reached"
        elif report.legality.ok:
            legality = "legality PASS"
        else:
            legality = "legality REJECT (" + "; ".join(report.legality.reasons) + ")"
        bound = " | runtime bound" if candidate.dynamic_trip else ""
        status = "VECTORIZED" if report.vectorized else "REJECTED"
        print(f"{location}  {status}  {stage} | {dependence} | {legality}{bound}")
        if args.trace:
            stopped = "scope" if not report.scope.ok else (
                "dependence" if report.dependence is not None and report.dependence.has_dependence
                else "legality" if report.legality is not None and not report.legality.ok
                else None
            )
            if stopped is None:
                print("  trace: passed all stages; directive added to source")
            else:
                print(f"  trace: stopped at {stopped}")
    if args.metrics:
        print("metrics: not available for C input")
    if args.verify:
        print("verify: toy IR only")
    display_source = transformed_source(
        source_text, candidates, entries, width=display_width
    )
    print("\nTransformed C source (accepted loops strip-mined; rejected loops unchanged):")
    print(display_source)
    if args.emit_c:
        print(f"\nWrote {args.emit_c}")
    return 0


def _dependence_text(dep) -> str:
    distance = "" if dep.distance is None else f", distance {dep.distance}"
    return (
        f"{dep.kind}: {dep.first.rendered} ({dep.first.role}) / "
        f"{dep.second.rendered} ({dep.second.role}){distance}"
    )


def _annotated_source(path: Path, candidates, entries) -> str:
    """Return the original C source with directives on accepted loops only."""
    source_text = path.read_text(encoding="utf-8")
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
    # A helper used by several accepted loops would otherwise be annotated
    # once per loop.
    insertions = list(dict.fromkeys(insertions))
    for offset, insertion in sorted(insertions, key=lambda item: item[0], reverse=True):
        source_text = _insert_directive(source_text, offset, insertion)
    return source_text


def _declared_width(source: str) -> int | None:
    """Read ``#pragma avlo width(N)`` from the original C source."""
    match = re.search(
        r"^\s*#\s*pragma\s+avlo\s+width\s*\(\s*(\d+)\s*\)",
        source,
        re.MULTILINE,
    )
    if match is None:
        return None
    value = int(match.group(1))
    return value if value >= 1 else None


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
