"""Unit tests for the strip-mining transformer."""
from __future__ import annotations

from avlo.parser import parse_text
from avlo.transform import transform


def test_transform_emits_vector_pseudo_ops():
    loop = parse_text("vector_width 4\nloop i = 0 to 8\n    c[i] = a[i] + b[i]\nend\n")
    transformed = transform(loop)
    assert [op.op for op in transformed.vector_body] == ["VLOAD", "VLOAD", "VADD", "VSTORE"]
    assert transformed.vector_trip == 8
    assert transformed.remainder_trip == 0


def test_transform_broadcasts_scalars():
    loop = parse_text("vector_width 4\nloop i = 0 to 8\n    y[i] = alpha * x[i]\nend\n")
    transformed = transform(loop)
    assert "VBCAST" in [op.op for op in transformed.vector_body]


def test_trip_partition_invariants():
    loop = parse_text("vector_width 4\nloop i = 0 to 101\n    c[i] = a[i] + b[i]\nend\n")
    transformed = transform(loop)
    assert transformed.vector_trip + transformed.remainder_trip == loop.trip
    assert transformed.vector_trip % transformed.vector_width == 0
