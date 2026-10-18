"""Compile and compare each original C example with AVLO's emitted source.

Run with ``uv run python scripts/e2e_c_examples.py``. Requires GCC (or a
compatible compiler selected through ``CC``) with OpenMP SIMD support.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=capture,
    )


def main() -> int:
    compiler = shlex.split(os.environ.get("CC", "gcc"))
    if not compiler:
        raise SystemExit("CC must name a C compiler")
    sources = sorted(EXAMPLES.glob("*.c"))
    if not sources:
        raise SystemExit("no C examples found")

    with tempfile.TemporaryDirectory(prefix="avlo-c-e2e-") as temporary:
        work = Path(temporary)
        for number, source in enumerate(sources):
            generated = work / f"{number}-{source.stem}.simd.c"
            analysis = run(
                [sys.executable, "-m", "avlo", str(source), "--json"], capture=True
            ).stdout
            run([
                sys.executable, "-m", "avlo", str(source), "--emit-c", str(generated)
            ], capture=True)

            original_binary = work / f"{number}-original"
            emitted_binary = work / f"{number}-emitted"
            flags = ["-std=c11", "-O2", "-fopenmp-simd"]
            if "int main(" not in source.read_text(encoding="utf-8"):
                run(compiler + flags + ["-c", str(generated), "-o", str(work / f"{number}.o")])
                print(f"{source.name}: PASS (non-runnable translation unit compiles)")
                continue

            for input_source, binary in ((source, original_binary), (generated, emitted_binary)):
                run(compiler + flags + [str(input_source), "-lm", "-o", str(binary)])
            before = run([str(original_binary)], capture=True).stdout
            after = run([str(emitted_binary)], capture=True).stdout
            if before != after:
                raise SystemExit(
                    f"{source.name}: output mismatch\n"
                    f"original:  {before!r}\nemitted:   {after!r}\n"
                    f"analysis:  {analysis}"
                )
            print(f"{source.name}: PASS ({before.strip()})")

    print(f"Validated {len(sources)} C examples.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
