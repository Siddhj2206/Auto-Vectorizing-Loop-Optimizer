"""Unit tests for the offset-based dependence analysis."""
from __future__ import annotations

from avlo.dependence import analyze
from avlo.parser import parse_text


def test_dependence_distance_of_minus_one():
    loop = parse_text("loop i = 1 to 11\n    a[i] = a[i-1] + 1\nend\n")
    result = analyze(loop)
    assert result.has_dependence
    assert result.deps[0].distance == -1


def test_same_offset_is_not_loop_carried():
    loop = parse_text("loop i = 0 to 10\n    y[i] = x[i] + y[i]\nend\n")
    assert not analyze(loop).has_dependence


def test_gcd_disproves_dependence_for_disjoint_strides():
    # a[2*i] and a[2*i+1] never coincide: gcd(2, 2) = 2 does not divide 1.
    loop = parse_text("loop i = 0 to 10\n    a[2*i] = a[2*i+1] + 1\nend\n")
    assert not analyze(loop).has_dependence
