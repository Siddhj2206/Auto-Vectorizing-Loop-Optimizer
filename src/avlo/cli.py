"""Command-line entry point: ``avlo <file.loop>``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .executor import verify
from .parser import ParseError, parse_file
from .pipeline import analyze
from .report import format_report, to_dict


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="avlo",
        description=(
            "Auto-Vectorizing Loop Optimizer: classify a toy-IR loop and, when it is "
            "dependency-free and legal, strip-mine it into a vector main loop plus a "
            "scalar remainder loop."
        ),
    )
    parser.add_argument(
        "loop_file",
        type=Path,
        help="path to a .loop file written in the toy IR text format",
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
            "inputs and check that they produce the same arrays"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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


if __name__ == "__main__":
    raise SystemExit(main())
