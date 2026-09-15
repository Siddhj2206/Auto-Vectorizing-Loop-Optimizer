"""Equivalence tests.

The transformed loop must compute exactly the same array values as the
original scalar loop. These tests actually execute both forms.
"""
from __future__ import annotations

from avlo.executor import verify
from avlo.parser import parse_text
from avlo.pipeline import VECTORIZED, analyze


def check(src: str) -> None:
    loop = parse_text(src)
    report = analyze(loop)
    assert report.status == VECTORIZED, report.reason
    result = verify(loop)
    assert result.equal, result.mismatches


def test_elementwise_add_is_equivalent():
    check("vector_width 4\nloop i = 0 to 100\n    c[i] = a[i] + b[i]\nend\n")


def test_elementwise_mul_sub_is_equivalent():
    check("vector_width 4\nloop i = 0 to 64\n    c[i] = a[i] * b[i] - a[i]\nend\n")


def test_saxpy_is_equivalent():
    check("vector_width 4\nloop i = 0 to 100\n    y[i] = alpha * x[i] + y[i]\nend\n")


def test_shifted_read_is_equivalent():
    check("vector_width 4\nloop i = 1 to 41\n    c[i] = a[i-1] + b[i]\nend\n")


def test_uneven_trip_is_equivalent():
    check("vector_width 4\nloop i = 0 to 101\n    c[i] = a[i] + b[i]\nend\n")


def test_small_trip_is_equivalent():
    check("vector_width 4\nloop i = 0 to 3\n    c[i] = a[i] + b[i]\nend\n")


def test_empty_loop_is_equivalent():
    check("vector_width 4\nloop i = 0 to 0\n    c[i] = a[i] + b[i]\nend\n")


def test_every_vector_width_is_equivalent():
    for width in (1, 2, 3, 4, 8):
        check(
            f"vector_width {width}\nloop i = 0 to 37\n"
            f"    c[i] = a[i] * b[i] - a[i]\nend\n"
        )
