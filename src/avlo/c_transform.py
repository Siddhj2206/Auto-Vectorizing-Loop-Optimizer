"""Display-only strip-mining for accepted C loops.

The real artifact remains the source written by ``--emit-c`` (the original C
with OpenMP SIMD directives). This module produces the representation printed
in the report: the accepted loop rewritten as a strip-mined main loop with V
copies of the body plus a scalar remainder loop. It is illustrative text, not
compiled or executed.
"""
from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass

from .c_frontend import CLoop


@dataclass(frozen=True)
class LoopSpan:
    start: int
    header_end: int
    body_start: int
    body_end: int
    end: int
    braced: bool


def source_offset(text: str, line: int, column: int) -> int:
    """Convert a one-based line/column to a character offset."""
    offset = 0
    for current, content in enumerate(text.splitlines(keepends=True), start=1):
        if current == line:
            return offset + min(max(column - 1, 0), len(content.rstrip("\r\n")))
        offset += len(content)
    return len(text)


def _skip_blank(text: str, index: int) -> int:
    while index < len(text):
        if text[index].isspace():
            index += 1
        elif text.startswith("//", index):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline + 1
        elif text.startswith("/*", index):
            close = text.find("*/", index + 2)
            index = len(text) if close < 0 else close + 2
        else:
            return index
    return index


def _skip_literal(text: str, index: int) -> int:
    quote = text[index]
    index += 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == quote:
            return index + 1
        else:
            index += 1
    return index


def _match(text: str, index: int, opening: str, closing: str) -> int:
    depth = 0
    while index < len(text):
        char = text[index]
        if char in "\"'":
            index = _skip_literal(text, index)
            continue
        if text.startswith("//", index) or text.startswith("/*", index):
            index = _skip_blank(text, index)
            continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)


def find_loop_span(text: str, start: int) -> LoopSpan:
    """Find the extent of the ``for`` statement beginning at ``start``."""
    index = _skip_blank(text, start + 3)
    header_end = _match(text, index, "(", ")")
    body = _skip_blank(text, header_end)
    if body < len(text) and text[body] == "{":
        end = _match(text, body, "{", "}")
        return LoopSpan(start, header_end, body + 1, end - 1, end, True)

    depth = 0
    index = body
    while index < len(text):
        char = text[index]
        if char in "\"'":
            index = _skip_literal(text, index)
            continue
        if text.startswith("//", index) or text.startswith("/*", index):
            index = _skip_blank(text, index)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == ";" and depth == 0:
            return LoopSpan(start, header_end, body, index + 1, index + 1, False)
        index += 1
    return LoopSpan(start, header_end, body, len(text), len(text), False)


def _split_semicolons(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char in "\"'":
            index = _skip_literal(text, index)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == ";" and depth == 0:
            parts.append(text[start:index])
            start = index + 1
        index += 1
    parts.append(text[start:])
    return parts


def _header_parts(text: str, span: LoopSpan) -> list[str] | None:
    header = text[span.start:span.header_end]
    match = re.match(r"for\s*\((.*)\)\s*$", header, re.S)
    if match is None:
        return None
    parts = _split_semicolons(match.group(1))
    if len(parts) != 3:
        return None
    return [part.strip() for part in parts]


def _step_value(text: str, iv: str) -> int | None:
    name = re.escape(iv)
    patterns = [
        (rf"^\+\+\s*{name}$", 1),
        (rf"^{name}\s*\+\+$", 1),
        (rf"^--\s*{name}$", -1),
        (rf"^{name}\s*--$", -1),
    ]
    for pattern, value in patterns:
        if re.match(pattern, text):
            return value
    for pattern, sign in (
        (rf"^{name}\s*\+=\s*(\d+)$", 1),
        (rf"^{name}\s*-=\s*(\d+)$", -1),
        (rf"^{name}\s*=\s*{name}\s*\+\s*(\d+)$", 1),
        (rf"^{name}\s*=\s*{name}\s*-\s*(\d+)$", -1),
        (rf"^{name}\s*=\s*(\d+)\s*\+\s*{name}$", 1),
    ):
        match = re.match(pattern, text)
        if match:
            return sign * int(match.group(1))
    return None


def _offset_expr(iv: str, delta: int) -> str:
    if delta == 0:
        return iv
    if delta > 0:
        return f"{iv} + {delta}"
    return f"{iv} - {abs(delta)}"


def _substitute(text: str, iv: str, delta: int) -> str:
    """Replace identifier ``iv`` with ``(iv +/- delta)`` outside literals."""
    if delta == 0:
        return text
    replacement = f"({_offset_expr(iv, delta)})"
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in "\"'":
            end = _skip_literal(text, index)
            out.append(text[index:end])
            index = end
        elif text.startswith("//", index):
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            out.append(text[index:end])
            index = end
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = len(text) if end < 0 else end + 2
            out.append(text[index:end])
            index = end
        elif char.isalpha() or char == "_":
            end = index + 1
            while end < len(text) and (text[end].isalnum() or text[end] == "_"):
                end += 1
            word = text[index:end]
            out.append(replacement if word == iv else word)
            index = end
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _tidy(copy: str, iv: str) -> str:
    """Drop parentheses where the added offset is already unambiguous."""
    name = re.escape(iv)
    copy = re.sub(rf"\[\({name} ([+-]) (\d+)\)\]", rf"[{iv} \1 \2]", copy)
    copy = re.sub(rf"= \({name} ([+-]) (\d+)\);", rf"= {iv} \1 \2;", copy)
    return copy


def _indent_for(text: str, start: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    prefix = text[line_start:start]
    return prefix[:len(prefix) - len(prefix.lstrip())]


def strip_mined(text: str, span: LoopSpan, candidate: CLoop, width: int = 4) -> str | None:
    """Return a strip-mined representation, or ``None`` if not supported."""
    parts = _header_parts(text, span)
    if parts is None:
        return None
    init, condition, step_text = parts
    iv = candidate.loop.iv if candidate.loop is not None else ""
    step = _step_value(step_text, iv)
    if not step:
        return None

    match = re.match(rf"^{re.escape(iv)}\s*(<=|>=|<|>)\s*(.+)$", condition, re.S)
    if match is None:
        return None
    operator = match.group(1)
    if (step > 0 and operator not in ("<", "<=")) or (
        step < 0 and operator not in (">", ">=")
    ):
        return None
    bound = match.group(2).strip()
    offset = (width - 1) * step
    increment = width * step
    main_condition = f"{_offset_expr(iv, offset)} {operator} {bound}"
    main_step = (
        f"{iv} += {increment}" if increment > 0 else f"{iv} -= {abs(increment)}"
    )

    body = text[span.body_start:span.body_end]
    core = textwrap.dedent(body.strip("\n"))
    indent = _indent_for(text, span.start)
    inner = indent + "    "

    lines = ["{"]
    lines.append(f"{inner}{init};")
    lines.append(f"{inner}for (; {main_condition}; {main_step}) {{")
    for lane in range(width):
        copy = _tidy(_substitute(core, iv, lane * step), iv)
        for line in copy.splitlines():
            lines.append(f"{inner}    {line}" if line.strip() else "")
    lines.append(f"{inner}}}")
    lines.append(f"{inner}for (; {condition}; {step_text}) {{")
    for line in core.splitlines():
        lines.append(f"{inner}    {line}" if line.strip() else "")
    lines.append(f"{inner}}}")
    lines.append(f"{indent}}}")
    return "\n".join(lines)


def transformed_source(
    text: str, candidates: list[CLoop], entries: list[dict], width: int = 4
) -> str:
    """Rewrite accepted loops in the source for display; leave rejections as-is."""
    edits: list[tuple[int, int, str]] = []
    for candidate, entry in zip(candidates, entries):
        if entry.get("status") != "VECTORIZED":
            continue
        start = source_offset(text, candidate.line, candidate.column)
        span = find_loop_span(text, start)
        replacement = strip_mined(text, span, candidate, width)
        if replacement is not None:
            edits.append((span.start, span.end, replacement))
            continue
        # The loop was accepted but its step is not a positive constant; show
        # the directive-only edit instead of an unrolled form.
        indent = _indent_for(text, start)
        edits.append((start, start, f"#pragma omp simd\n{indent}"))

    for start, end, replacement in sorted(edits, key=lambda item: item[0], reverse=True):
        text = text[:start] + replacement + text[end:]
    return text
