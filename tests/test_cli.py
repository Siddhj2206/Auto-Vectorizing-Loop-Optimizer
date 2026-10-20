"""CLI smoke tests: drive the entry point the way the evaluator will."""
from __future__ import annotations

from pathlib import Path

from avlo.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _write(tmp_path: Path, body: str) -> Path:
    loop = tmp_path / "loop.loop"
    loop.write_text(body, encoding="utf-8")
    return loop


def test_cli_json_output(tmp_path, capsys):
    loop = _write(tmp_path, "vector_width 4\nloop i = 0 to 8\n    c[i] = a[i] + b[i]\nend\n")
    assert main([str(loop), "--json"]) == 0
    assert '"status": "VECTORIZED"' in capsys.readouterr().out


def test_cli_verify_flag(tmp_path, capsys):
    loop = _write(tmp_path, "vector_width 4\nloop i = 0 to 8\n    c[i] = a[i] + b[i]\nend\n")
    assert main([str(loop), "--verify"]) == 0
    assert "Equivalence check: PASS" in capsys.readouterr().out


def test_cli_missing_file(tmp_path, capsys):
    assert main([str(tmp_path / "nope.loop")]) == 2
    assert "file not found" in capsys.readouterr().err


def test_every_example_runs(capsys):
    for path in sorted(EXAMPLES.glob("*.c")):
        assert main([str(path)]) == 0, path
    output = capsys.readouterr().out
    assert "Transformed C source" in output
    assert "for (; i" in output


def test_perfect_loop_nest_vectorizes_innermost_loop(capsys):
    path = EXAMPLES / "nested_loop.c"
    assert main([str(path)]) == 0
    output = capsys.readouterr().out
    assert "VECTORIZED" in output
    assert "UNSUPPORTED" not in output


def test_nested_recurrence_is_rejected(capsys):
    path = EXAMPLES / "nested_recurrence.c"
    assert main([str(path)]) == 0
    output = capsys.readouterr().out
    assert "dependence RAW" in output
    assert "REJECTED" in output


def test_emit_c_annotates_nested_control_flow(tmp_path):
    output = tmp_path / "nested_branch.simd.c"
    assert main([str(EXAMPLES / "nested_branch.c"), "--emit-c", str(output)]) == 0
    source = output.read_text(encoding="utf-8")
    assert source.count("#pragma omp simd") >= 1
    assert "if (flag[i])" in source


def test_emit_c_inserts_directives_at_each_same_line_loop(tmp_path):
    output = tmp_path / "compact_loops.simd.c"
    assert main([str(EXAMPLES / "compact_loops.c"), "--emit-c", str(output)]) == 0
    source = output.read_text(encoding="utf-8")
    assert source.count("#pragma omp simd") == 2
    assert "#pragma omp simd\nfor (int i" in source
    assert "#pragma omp simd\nfor (int j" in source


def test_early_exit_is_not_annotated(tmp_path, capsys):
    source = tmp_path / "early_exit.c"
    emitted = tmp_path / "early_exit.simd.c"
    source.write_text(
        "void f(int n, int * restrict a) {\n"
        "  for (int i = 0; i < n; ++i) {\n"
        "    if (a[i] < 0) break;\n"
        "    a[i] += 1;\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    assert main([str(source), "--emit-c", str(emitted)]) == 0
    output = capsys.readouterr().out
    assert "UNSUPPORTED" in output
    assert "#pragma omp simd" not in emitted.read_text(encoding="utf-8")
