"""Unit tests for the toy IR model, the text parser and affine reduction."""
from __future__ import annotations

import pytest

from avlo.ir import Index
from avlo.parser import ParseError, parse_text


def test_affine_index_reduction():
    loop = parse_text("loop i = 0 to 10\n    c[2*i+1] = a[i]\nend\n")
    assert loop.statements[0].target.index == Index(2, 1)


def test_affine_negative_offset():
    loop = parse_text("loop i = 0 to 10\n    a[i-1] = b[i]\nend\n")
    assert loop.statements[0].target.index == Index(1, -1)


def test_non_affine_index_is_kept_for_rejection():
    loop = parse_text("loop i = 0 to 10\n    a[i*i] = b[i]\nend\n")
    assert loop.statements[0].target.index is None
    assert loop.statements[0].target.raw_index is not None


def test_render_preserves_precedence():
    loop = parse_text("loop i = 0 to 10\n    c[i] = (a[i] + b[i]) * 2\nend\n")
    assert loop.statements[0].render("i") == "c[i] = (a[i] + b[i]) * 2"


def test_parse_error_on_missing_end():
    with pytest.raises(ParseError):
        parse_text("loop i = 0 to 10\n    c[i] = a[i]\n")
