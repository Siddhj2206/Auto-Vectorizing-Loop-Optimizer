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


def test_every_example_runs():
    for path in sorted(EXAMPLES.glob("*.loop")):
        assert main([str(path)]) == 0, path
