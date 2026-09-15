"""Known-answer taxonomy tests T-01 .. T-11 from the project test plan.

Each test feeds a small loop through the full pipeline and asserts the
classification and strip-mining decision recorded in the Review 1 test plan.
"""
from __future__ import annotations

from avlo.parser import parse_text
from avlo.pipeline import REJECTED, VECTORIZED, analyze


def build(body: str, *, trip: int = 100, width: int = 4) -> str:
    return f"vector_width {width}\nloop i = 0 to {trip}\n{body}\nend\n"


def run(body: str, *, trip: int = 100, width: int = 4):
    return analyze(parse_text(build(body, trip=trip, width=width)))


# --------------------------------------------------------------------------
# Positive cases: independent per-element read/write
# --------------------------------------------------------------------------
def test_t01_elementwise_add():
    report = run("    c[i] = a[i] + b[i]")
    assert report.status == VECTORIZED
    assert report.dependence is not None
    assert not report.dependence.has_dependence


def test_t02_elementwise_sub():
    assert run("    c[i] = a[i] - b[i]").status == VECTORIZED


def test_t03_elementwise_mul():
    assert run("    c[i] = a[i] * b[i]").status == VECTORIZED


def test_t04_array_copy():
    assert run("    b[i] = a[i]").status == VECTORIZED


def test_t05_saxpy():
    report = run("    y[i] = alpha * x[i] + y[i]")
    assert report.status == VECTORIZED
    assert report.dependence is not None
    assert not report.dependence.has_dependence


# --------------------------------------------------------------------------
# Negative cases: dependency or unsupported construct
# --------------------------------------------------------------------------
def test_t06_recurrence_is_not_vectorizable():
    report = run("    a[i] = a[i-1] + 1")
    assert report.status == REJECTED
    assert report.dependence is not None and report.dependence.has_dependence
    assert report.transformed is None


def test_t07_cross_offset_is_not_vectorizable():
    report = run("    a[i+1] = a[i] * 2")
    assert report.status == REJECTED
    assert report.dependence is not None and report.dependence.has_dependence
    assert report.transformed is None


def test_t08_function_call_is_rejected():
    report = run("    c[i] = a[i] + foo(b[i])")
    assert report.status == REJECTED
    assert report.legality is not None and not report.legality.ok
    assert report.transformed is None


# --------------------------------------------------------------------------
# Boundary cases: trip-count edge conditions
# --------------------------------------------------------------------------
def test_t09_trip_smaller_than_vector_width():
    report = run("    c[i] = a[i] + b[i]", trip=3, width=4)
    assert report.status == VECTORIZED
    transformed = report.transformed
    assert transformed is not None
    assert transformed.vector_trip == 0
    assert transformed.remainder_trip == 3
    assert not transformed.has_vector_loop
    assert transformed.has_remainder_loop


def test_t10_trip_not_divisible_by_vector_width():
    report = run("    c[i] = a[i] + b[i]", trip=101, width=4)
    transformed = report.transformed
    assert transformed is not None
    assert transformed.vector_trip == 100
    assert transformed.remainder_trip == 1
    assert transformed.has_vector_loop
    assert transformed.has_remainder_loop


def test_t11_empty_loop_is_a_noop():
    report = run("    c[i] = a[i] + b[i]", trip=0, width=4)
    assert report.status == VECTORIZED
    transformed = report.transformed
    assert transformed is not None
    assert transformed.vector_trip == 0
    assert transformed.remainder_trip == 0
    assert not transformed.has_vector_loop
    assert not transformed.has_remainder_loop
