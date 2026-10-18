"""C source front end for the conservative, loop-oriented AVLO subset.

The C parser builds syntax and scope information; AVLO then lowers only loops
whose bounds and body fit its current analysis IR. Unsupported loops are
reported with source locations instead of being approximated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from pycparser import c_ast, c_parser, c_generator

from .ir import BinOp, Call, Cast, Expr, Index, Loop, Num, Ref, Scalar, Statement, Unary
from .parser import ParseError

C_BINARY_OPS = {
    "+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>",
    "==", "!=", "<", "<=", ">", ">=", "&&", "||",
}
PURE_MATH_CALLS = {
    "abs", "fabs", "fabsf", "sqrt", "sqrtf", "cbrt", "sin", "sinf",
    "cos", "cosf", "tan", "exp", "expf", "log", "logf", "floor",
    "ceil", "trunc", "round", "fmin", "fmax", "fminf", "fmaxf",
    "pow", "powf", "fmod", "fmodf", "asin", "acos", "atan", "sinh",
    "cosh", "tanh", "log10", "log2",
}


@dataclass
class CLoop:
    loop: Loop | None
    line: int
    reason: str = ""
    dynamic_trip: bool = False
    reductions: list[tuple[str, str]] | None = None
    declare_simd: list[tuple[str, int, int]] | None = None
    column: int = 1


def _prepare_source(text: str) -> tuple[str, int, list[list[int]]]:
    """Remove directives while retaining simple integer #define constants."""
    text = _strip_comments(text)
    defines: dict[str, str] = {}
    lines: list[str] = []
    for line in text.splitlines():
        if re.match(r"\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b", line):
            raise ParseError("conditional preprocessor branches are not supported yet")
        match = re.match(
            r"\s*#\s*define\s+([A-Za-z_]\w*)\s+([0-9a-fA-FxXuUlL()+*/%\- \t]+)\s*$",
            line,
        )
        if match:
            defines[match.group(1)] = match.group(2)
            lines.append("")
        elif re.match(r"\s*#", line):
            # Headers and conditional compilation are outside this front end.
            lines.append("")
        else:
            lines.append(line)
    expanded_lines: list[str] = []
    column_maps: list[list[int]] = []
    for line in lines:
        expanded = line
        origin = list(range(len(line)))
        for name, value in defines.items():
            pattern = re.compile(rf"\b{re.escape(name)}\b")
            pieces: list[str] = []
            mapped: list[int] = []
            end = 0
            for match in pattern.finditer(expanded):
                pieces.append(expanded[end:match.start()])
                mapped.extend(origin[end:match.start()])
                pieces.append(value)
                mapped.extend([origin[match.start()]] * len(value))
                end = match.end()
            if end:
                pieces.append(expanded[end:])
                mapped.extend(origin[end:])
                expanded = "".join(pieces)
                origin = mapped
        expanded_lines.append(expanded)
        column_maps.append(origin)
    source = "\n".join(expanded_lines)
    common_types = {
        "size_t": "unsigned long",
        "ptrdiff_t": "long",
        "int8_t": "signed char",
        "uint8_t": "unsigned char",
        "int16_t": "short",
        "uint16_t": "unsigned short",
        "int32_t": "int",
        "uint32_t": "unsigned int",
        "int64_t": "long long",
        "uint64_t": "unsigned long long",
        "intptr_t": "long",
        "uintptr_t": "unsigned long",
        "bool": "_Bool",
    }
    preamble = []
    for name, c_type in common_types.items():
        if re.search(rf"\b{re.escape(name)}\b", source) and not re.search(
            rf"\btypedef\b[^;]*\b{re.escape(name)}\s*;", source
        ):
            preamble.append(f"typedef {c_type} {name};")
    return (
        "\n".join(preamble + [source]),
        len(preamble),
        [[] for _ in preamble] + column_maps,
    )


def _original_location(coord, line_offset: int, column_maps: list[list[int]]) -> tuple[int, int]:
    line = coord.line - line_offset if coord else 0
    if not coord:
        return line, 1
    parsed_line = coord.line - 1
    parsed_column = coord.column - 1
    mapping = column_maps[parsed_line] if 0 <= parsed_line < len(column_maps) else []
    original_column = mapping[parsed_column] + 1 if parsed_column < len(mapping) else parsed_column + 1
    return line, original_column


def _declaration_start(source: str, line: int, column: int) -> tuple[int, int]:
    """Return the first token of a function declaration, before its name."""
    lines = source.splitlines(keepends=True)
    offset = sum(len(item) for item in lines[:line - 1]) + column - 1
    boundary = max(source.rfind(mark, 0, offset) for mark in (";", "{", "}"))
    # Preprocessor lines are not declaration text, but ordinary newlines may
    # split a function's return type and declarator.
    before = source[:offset]
    directive = before.rfind("\n#")
    if directive >= 0:
        directive += 1
    elif before.startswith("#"):
        directive = 0
    if directive >= 0:
        directive_end = before.find("\n", directive)
        if directive_end >= 0:
            boundary = max(boundary, directive_end)
    start = boundary + 1
    while start < offset and source[start].isspace():
        start += 1
    prefix = source[:start]
    start_line = prefix.count("\n") + 1
    start_column = start - (prefix.rfind("\n") + 1) + 1
    return start_line, start_column


def _strip_comments(text: str) -> str:
    """Replace C comments with whitespace while preserving line locations."""
    out: list[str] = []
    i = 0
    state = "code"
    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if char == '"':
                state = "string"
                out.append(char)
            elif char == "'":
                state = "char"
                out.append(char)
            elif char == "/" and nxt == "/":
                state = "line_comment"
                out.extend((" ", " "))
                i += 1
            elif char == "/" and nxt == "*":
                state = "block_comment"
                out.extend((" ", " "))
                i += 1
            else:
                out.append(char)
        elif state in ("string", "char"):
            out.append(char)
            if char == "\\" and i + 1 < len(text):
                i += 1
                out.append(text[i])
            elif (state == "string" and char == '"') or (state == "char" and char == "'"):
                state = "code"
        elif state == "line_comment":
            if char == "\n":
                out.append(char)
                state = "code"
            else:
                out.append(" ")
        else:
            if char == "*" and nxt == "/":
                out.extend((" ", " "))
                state = "code"
                i += 1
            else:
                out.append("\n" if char == "\n" else " ")
        i += 1
    return "".join(out)


def _integer(node) -> int:
    if isinstance(node, c_ast.Constant) and node.type == "int":
        raw = re.sub(r"[uUlL]+$", "", node.value)
        return int(raw, 0)
    if isinstance(node, c_ast.UnaryOp) and node.op in ("+", "-"):
        value = _integer(node.expr)
        return value if node.op == "+" else -value
    if isinstance(node, c_ast.BinaryOp) and node.op in ("+", "-", "*", "/", "%"):
        left, right = _integer(node.left), _integer(node.right)
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if right == 0:
            raise ValueError("division by zero in constant loop bound")
        quotient = abs(left) // abs(right)
        if (left < 0) != (right < 0):
            quotient = -quotient
        return quotient if node.op == "/" else left - quotient * right
    raise ValueError("loop bounds and initial values must be integer constants")


def _type_categories(ast) -> dict[str, str]:
    signed = {"signed", "int", "short", "long", "int8_t", "int16_t", "int32_t",
              "int64_t", "intptr_t", "ptrdiff_t", "_Bool", "bool"}
    unsigned = {"unsigned", "size_t", "uint8_t", "uint16_t", "uint32_t", "uint64_t", "uintptr_t"}
    floating = {"float", "double", "_Complex"}
    aliases: dict[str, str] = {}

    def base_names(ctype):
        while not isinstance(ctype, c_ast.TypeDecl):
            if isinstance(ctype, c_ast.PtrDecl):
                return None
            ctype = getattr(ctype, "type", None)
            if ctype is None:
                return None
        if isinstance(ctype.type, c_ast.IdentifierType):
            return set(ctype.type.names)
        return None

    def category(names):
        if names is None:
            return "pointer"
        if names & unsigned:
            return "unsigned"
        if "void" in names:
            return "void"
        if names & floating:
            return "floating"
        if names & signed:
            return "signed"
        if len(names) == 1 and next(iter(names)) in aliases:
            return aliases[next(iter(names))]
        return "unknown"

    for node in ast.ext:
        if isinstance(node, c_ast.Typedef):
            current = node.type
            is_volatile = False
            while current is not None:
                if "volatile" in getattr(current, "quals", ()):
                    is_volatile = True
                current = getattr(current, "type", None)
                if isinstance(current, (c_ast.IdentifierType, c_ast.Struct, c_ast.Union)):
                    break
            aliases[node.name] = "volatile" if is_volatile else category(base_names(node.type))
    kinds: dict[str, set[str]] = {}
    class Declarations(c_ast.NodeVisitor):
        def visit_Decl(self, node):
            if node.name:
                kind = category(base_names(node.type))
                current = node.type
                is_volatile = False
                while current is not None:
                    if "volatile" in getattr(current, "quals", ()):
                        is_volatile = True
                    current = getattr(current, "type", None)
                    if isinstance(current, (c_ast.IdentifierType, c_ast.Struct, c_ast.Union)):
                        break
                if is_volatile:
                    kind = "volatile"
                kinds.setdefault(node.name, set()).add(kind)
            self.generic_visit(node)
        def visit_Enumerator(self, node):
            kinds.setdefault(node.name, set()).add("signed")
    Declarations().visit(ast)
    for alias, kind in aliases.items():
        kinds.setdefault(alias, set()).add(kind)
    return {name: next(iter(values)) if len(values) == 1 else "unknown"
            for name, values in kinds.items()}


def _expression_ids(node) -> set[str]:
    names: set[str] = set()
    class Names(c_ast.NodeVisitor):
        def visit_ID(self, item):
            names.add(item.name)
    Names().visit(node)
    return names


@dataclass(frozen=True)
class _IndexRebase:
    start: int | None
    step: int
    start_expression: str | None
    start_names: frozenset[str]


def _rebase_ref(ref: Ref, context: _IndexRebase) -> Ref:
    if ref.index is None:
        return ref
    coefficient = ref.index.coeff
    offset = ref.index.offset
    symbolic = ref.symbolic_offset
    names = set(ref.symbolic_names)
    index_names = set(ref.index_names)
    if context.start is None:
        if coefficient and context.start_expression:
            start_term = f"({coefficient}) * ({context.start_expression})"
            symbolic = f"({symbolic}) + ({start_term})" if symbolic else start_term
            names.update(context.start_names)
            index_names.update(context.start_names)
    else:
        offset += coefficient * context.start
    return replace(
        ref,
        index=Index(coefficient * context.step, offset),
        symbolic_offset=symbolic,
        symbolic_names=frozenset(names),
        index_names=frozenset(index_names),
    )


def _rebase_expr(expr: Expr, context: _IndexRebase) -> Expr:
    if isinstance(expr, Ref):
        return _rebase_ref(expr, context)
    if isinstance(expr, BinOp):
        return replace(
            expr,
            left=_rebase_expr(expr.left, context),
            right=_rebase_expr(expr.right, context),
        )
    if isinstance(expr, Call):
        return replace(expr, args=tuple(_rebase_expr(arg, context) for arg in expr.args))
    if isinstance(expr, (Cast, Unary)):
        return replace(expr, value=_rebase_expr(expr.value, context))
    return expr


def _expr(node, iv: str) -> Expr:
    if isinstance(node, c_ast.Constant):
        if node.type in ("int", "char"):
            return Num(_integer(node))
        if node.type in ("float", "double", "long double"):
            return Num(float(re.sub(r"[fFlL]$", "", node.value)))
        raise ValueError(f"unsupported constant type {node.type}")
    if isinstance(node, c_ast.ID):
        return Scalar(node.name)
    if isinstance(node, c_ast.ArrayRef):
        root = node.name
        prefix_names: set[str] = set()
        while isinstance(root, c_ast.ArrayRef):
            class PrefixIndex(c_ast.NodeVisitor):
                invalid = False
                def visit_ID(self, item):
                    self.names.add(item.name)
                    if item.name == iv:
                        self.invalid = True
                def visit_ArrayRef(self, item):
                    self.invalid = True
                def visit_FuncCall(self, item):
                    self.invalid = True
                def visit_UnaryOp(self, item):
                    if item.op in ("*", "p++", "p--", "++", "--"):
                        self.invalid = True
                    self.generic_visit(item)
            prefix = PrefixIndex()
            prefix.names = prefix_names
            prefix.visit(root.subscript)
            if prefix.invalid:
                raise ValueError(
                    "outer array dimensions must be loop-invariant and side-effect-free"
                )
            root = root.name
        if not isinstance(root, c_ast.ID):
            raise ValueError("indirect array access is unsupported")
        array_name = c_generator.CGenerator().visit(node.name)
        affine = _c_affine(node.subscript, iv)
        if affine is not None:
            coeff, offset, symbolic, names = affine
            return Ref(array_name, index=Index(coeff, offset),
                       symbolic_offset=symbolic, symbolic_names=frozenset(names),
                       index_names=frozenset(names | prefix_names | ({iv} if coeff else set())))
        index_expr = _expr(node.subscript, iv)
        return Ref(array_name, index=None, raw_index=index_expr,
                   index_names=frozenset(prefix_names | {iv}))
    if isinstance(node, c_ast.BinaryOp) and node.op in C_BINARY_OPS:
        return BinOp(node.op, _expr(node.left, iv), _expr(node.right, iv))
    if isinstance(node, c_ast.UnaryOp) and node.op in ("-", "+", "!", "~"):
        return Unary(node.op, _expr(node.expr, iv))
    if isinstance(node, c_ast.FuncCall):
        if not isinstance(node.name, c_ast.ID):
            raise ValueError("indirect function calls are unsupported")
        args = [] if node.args is None else [_expr(arg, iv) for arg in node.args]
        return Call(node.name.name, tuple(args))
    if isinstance(node, c_ast.Cast):
        return Cast(c_generator.CGenerator().visit(node.to_type), _expr(node.expr, iv))
    raise ValueError(f"unsupported expression: {type(node).__name__}")


def _c_affine(node, iv: str):
    """Affine C subscript with a loop-invariant symbolic offset."""
    generator = c_generator.CGenerator()
    if isinstance(node, c_ast.Constant) and node.type == "int":
        return (0, _integer(node), None, set())
    if isinstance(node, c_ast.ID):
        return (1, 0, None, set()) if node.name == iv else (0, 0, node.name, {node.name})
    if isinstance(node, c_ast.UnaryOp) and node.op in ("+", "-"):
        item = _c_affine(node.expr, iv)
        if item is None or node.op == "+":
            return item
        coeff, offset, symbolic, names = item
        return -coeff, -offset, (f"-({symbolic})" if symbolic else None), names
    if isinstance(node, c_ast.BinaryOp) and node.op in ("+", "-", "*", "/"):
        left, right = _c_affine(node.left, iv), _c_affine(node.right, iv)
        if left is None or right is None:
            return None
        lc, lo, ls, ln = left
        rc, ro, rs, rn = right
        names = ln | rn
        if node.op in ("+", "-"):
            sign = 1 if node.op == "+" else -1
            if ls is None:
                symbolic = rs if sign == 1 else (f"-({rs})" if rs else None)
            elif rs is None:
                symbolic = ls
            else:
                symbolic = f"({ls}) {node.op} ({rs})"
            return lc + sign * rc, lo + sign * ro, symbolic, names
        if node.op == "*":
            if lc and rc:
                return None
            if lc or rc:
                affine, constant = (left, right) if lc else (right, left)
                ac, ao, ass, an = affine
                cc, co, cs, cn = constant
                if cc != 0 or cs is not None or co == 0:
                    return None
                return ac * co, ao * co, ass, an
            if ls is None and rs is None:
                return 0, lo * ro, None, names
            return 0, lo * ro, generator.visit(node), names
        if rc != 0 or rs is not None or ro == 0:
            return None
        if lc % ro or lo % ro:
            return None
        symbolic = f"({ls}) / {ro}" if ls is not None else None
        return lc // ro, lo // ro, symbolic, names
    return None


def _dynamic_scalar_expression(node, iv: str) -> bool:
    valid = True
    class Check(c_ast.NodeVisitor):
        def visit_ID(self, item):
            nonlocal valid
            if item.name == iv:
                valid = False
        def visit_ArrayRef(self, item):
            nonlocal valid
            valid = False
        def visit_FuncCall(self, item):
            nonlocal valid
            valid = False
        def visit_Assignment(self, item):
            nonlocal valid
            valid = False
        def visit_UnaryOp(self, item):
            nonlocal valid
            if item.op in ("p++", "p--", "++", "--", "*"):
                valid = False
            self.generic_visit(item)
    Check().visit(node)
    return valid


def _loop_header(node: c_ast.For, type_categories: dict[str, str]):
    init = node.init
    start_names: set[str] = set()
    if isinstance(init, c_ast.DeclList) and len(init.decls) == 1:
        decl = init.decls[0]
        if decl.init is None or not isinstance(decl.type, c_ast.TypeDecl):
            raise ValueError("for initializer must declare one initialized scalar")
        iv = decl.name
        try:
            start = _integer(decl.init)
        except ValueError:
            start = None
        if start is None:
            ids = _expression_ids(decl.init)
            if not ids or not _dynamic_scalar_expression(decl.init, iv):
                raise ValueError("loop initializer must be a side-effect-free scalar expression")
            if any(type_categories.get(name) != type_categories.get(iv) for name in ids):
                raise ValueError("runtime loop initializer must match the induction variable type")
            start_names = ids
    elif isinstance(init, c_ast.Assignment) and init.op == "=" and isinstance(init.lvalue, c_ast.ID):
        iv = init.lvalue.name
        try:
            start = _integer(init.rvalue)
        except ValueError:
            start = None
        if start is None:
            ids = _expression_ids(init.rvalue)
            if not ids or not _dynamic_scalar_expression(init.rvalue, iv):
                raise ValueError("loop initializer must be a side-effect-free scalar expression")
            if any(type_categories.get(name) != type_categories.get(iv) for name in ids):
                raise ValueError("runtime loop initializer must match the induction variable type")
            start_names = ids
    else:
        raise ValueError("for initializer must be i = integer or int i = integer")
    iv_category = type_categories.get(iv)
    if iv_category not in ("signed", "unsigned"):
        raise ValueError("induction variable must have a supported integer type")

    cond = node.cond
    if not isinstance(cond, c_ast.BinaryOp) or cond.op not in ("<", "<=", ">", ">="):
        raise ValueError("loop condition must compare the induction variable with a bound")
    if not isinstance(cond.left, c_ast.ID) or cond.left.name != iv:
        raise ValueError("loop condition must compare the induction variable on the left")
    try:
        bound = _integer(cond.right)
    except ValueError:
        ids = _expression_ids(cond.right)
        if not ids or not _dynamic_scalar_expression(cond.right, iv):
            raise ValueError("loop bound must be an integer constant or side-effect-free scalar expression")
        if any(type_categories.get(name) != iv_category for name in ids):
            raise ValueError("runtime loop bound must match the induction variable type")
        bound = None

    step = None
    nxt = node.next
    if isinstance(nxt, c_ast.UnaryOp) and isinstance(nxt.expr, c_ast.ID) and nxt.expr.name == iv:
        if nxt.op in ("p++", "++"):
            step = 1
        elif nxt.op in ("p--", "--"):
            step = -1
    elif isinstance(nxt, c_ast.Assignment) and isinstance(nxt.lvalue, c_ast.ID) and nxt.lvalue.name == iv:
        if nxt.op in ("+=", "-="):
            amount = _integer(nxt.rvalue)
            step = amount if nxt.op == "+=" else -amount
        elif nxt.op == "=" and isinstance(nxt.rvalue, c_ast.BinaryOp):
            rhs = nxt.rvalue
            try:
                amount = _integer(rhs.right)
                if isinstance(rhs.left, c_ast.ID) and rhs.left.name == iv:
                    step = amount if rhs.op == "+" else -amount if rhs.op == "-" else None
            except ValueError:
                if rhs.op == "+":
                    try:
                        amount = _integer(rhs.left)
                        if isinstance(rhs.right, c_ast.ID) and rhs.right.name == iv:
                            step = amount
                    except ValueError:
                        pass
    if step is None or step == 0:
        raise ValueError("loop induction step must be a non-zero integer constant")
    if (cond.op in ("<", "<=") and step < 0) or (cond.op in (">", ">=") and step > 0):
        raise ValueError("loop step direction does not move toward its termination bound")
    if iv_category == "unsigned" and (step < 0 or step != 1 or cond.op in ("<=", ">=")):
        raise ValueError("unsigned loops require a unit positive step and strict bound")
    if iv_category == "unsigned" and (
        (start is not None and start < 0) or (bound is not None and bound < 0)
    ):
        raise ValueError("unsigned loops cannot use negative initial values or bounds")

    trip = None
    if start is not None and bound is not None:
        if step > 0:
            span = bound - start + (1 if cond.op == "<=" else 0)
        else:
            span = start - bound + (1 if cond.op == ">=" else 0)
        trip = max(0, (span + abs(step) - 1) // abs(step))
    start_expression = None if start is not None else c_generator.CGenerator().visit(
        init.decls[0].init if isinstance(init, c_ast.DeclList) else init.rvalue
    )
    return iv, start, trip, step, start_expression, start_names


def _body_statements(body, iv: str) -> tuple[list[Statement], list[tuple[str, str]], list[Ref], set[str]]:
    statements: list[Statement] = []
    reductions: list[tuple[str, str]] = []
    extra_reads: list[Ref] = []
    condition_scalars: set[str] = set()

    class ConditionAccesses(c_ast.NodeVisitor):
        def visit_ID(self, node):
            condition_scalars.add(node.name)
        def visit_ArrayRef(self, node):
            ref = _expr(node, iv)
            if isinstance(ref, Ref):
                extra_reads.append(ref)
            # For A[i][j], A[i] is only the base expression of the full
            # element access. Do not count it as a second memory read.
            self.visit(node.subscript)
        def visit_FuncCall(self, node):
            raise ValueError("function calls in branch conditions are unsupported")
        def visit_Assignment(self, node):
            raise ValueError("assignments in branch conditions are unsupported")
        def visit_UnaryOp(self, node):
            if node.op in ("*", "p++", "p--", "++", "--"):
                raise ValueError("pointer dereferences and updates in branch conditions are unsupported")
            self.generic_visit(node)

    def visit(node):
        if isinstance(node, c_ast.Compound):
            for child in node.block_items or []:
                visit(child)
            return
        if isinstance(node, c_ast.If):
            ConditionAccesses().visit(node.cond)
            visit(node.iftrue)
            if node.iffalse is not None:
                visit(node.iffalse)
            return
        if isinstance(node, c_ast.EmptyStatement):
            return
        if isinstance(node, c_ast.UnaryOp) and node.op in ("p++", "++", "p--", "--"):
            if isinstance(node.expr, c_ast.ArrayRef):
                target = _expr(node.expr, iv)
                if not isinstance(target, Ref):
                    raise ValueError("invalid array increment target")
                delta = 1 if node.op in ("p++", "++") else -1
                statements.append(Statement(target, BinOp("+", target, Num(delta))))
                return
            if isinstance(node.expr, c_ast.ID) and node.op in ("p++", "++"):
                reductions.append((node.expr.name, "+"))
                return
        if isinstance(node, c_ast.Assignment):
            if isinstance(node.lvalue, c_ast.ArrayRef) and node.op in ("=", "+=", "-=", "*=", "/=", "%="):
                target = _expr(node.lvalue, iv)
                if not isinstance(target, Ref):
                    raise ValueError("invalid array assignment target")
                value = _expr(node.rvalue, iv)
                if node.op != "=":
                    value = BinOp(node.op[0], target, value)
                statements.append(Statement(target, value))
                return
            reduction_op = {"+=": "+", "*=": "*"}.get(node.op)
            value = node.rvalue
            if (node.op == "=" and isinstance(node.lvalue, c_ast.ID)
                    and isinstance(value, c_ast.BinaryOp)
                    and value.op in ("+", "*")
                    and isinstance(value.left, c_ast.ID)
                    and value.left.name == node.lvalue.name):
                reduction_op = value.op
                value = value.right
            elif (node.op == "=" and isinstance(node.lvalue, c_ast.ID)
                    and isinstance(value, c_ast.BinaryOp)
                    and value.op in ("+", "*")
                    and isinstance(value.right, c_ast.ID)
                    and value.right.name == node.lvalue.name):
                reduction_op = value.op
                value = value.left
            if isinstance(node.lvalue, c_ast.ID) and reduction_op is not None:
                reductions.append((node.lvalue.name, reduction_op))
                expr = _expr(value, iv)
                if expr.calls():
                    raise ValueError("function calls in reductions are unsupported")
                if any(scalar.name == node.lvalue.name for scalar in expr.scalars()):
                    raise ValueError("reduction variable cannot occur in its own contribution")
                if any(ref.index is None or ref.index.coeff == 0 for ref in expr.reads()):
                    raise ValueError("reduction array reads must have affine non-broadcast indexes")
                extra_reads.extend(expr.reads())
                return
        raise ValueError("loop body supports array assignments, reductions and scalar if/else")

    visit(body)
    if not statements and not reductions:
        raise ValueError("empty loop body")
    if len(set(name for name, _ in reductions)) != len(reductions):
        raise ValueError("a reduction variable may be updated only once per loop body")
    reduction_names = {name for name, _ in reductions}
    if condition_scalars & reduction_names:
        raise ValueError("reduction variables cannot control branches in the loop")
    if any(reduction_names & {scalar.name for scalar in stmt.value.scalars()}
           for stmt in statements):
        raise ValueError("a reduction variable cannot be read by another loop statement")
    return statements, reductions, extra_reads, condition_scalars


def _single_nested_for(node):
    """Return the child loop when ``node`` is a perfect one-loop nest body."""
    if isinstance(node, c_ast.For):
        return node
    if isinstance(node, c_ast.Compound):
        items = node.block_items or []
        if len(items) == 1 and isinstance(items[0], c_ast.For):
            return items[0]
    return None


class _Loops(c_ast.NodeVisitor):
    def __init__(self, line_offset: int = 0,
                 pure_functions: dict[str, tuple[int, int]] | None = None,
                 type_categories: dict[str, str] | None = None,
                 column_maps: list[list[int]] | None = None):
        self.found: list[CLoop] = []
        self.unsafe_pointer_names: set[str] = set()
        self.pointer_names: set[str] = set()
        self.pointer_typedefs: set[str] = set()
        self.line_offset = line_offset
        self.column_maps = column_maps or []
        self.pure_functions = pure_functions or {}
        self.type_categories = type_categories or {}
        self.loop_stack: list[str] = []

    def _location(self, node) -> tuple[int, int]:
        return _original_location(node.coord, self.line_offset, self.column_maps)

    def _is_pointer_decl(self, decl) -> bool:
        return isinstance(decl.type, c_ast.PtrDecl) or (
            isinstance(decl.type, c_ast.TypeDecl)
            and isinstance(decl.type.type, c_ast.IdentifierType)
            and bool(set(decl.type.type.names) & self.pointer_typedefs)
        )

    def _unsafe_pointer_decl(self, decl, array_parameter: bool = False) -> bool:
        if isinstance(decl.type, c_ast.PtrDecl):
            return "restrict" not in decl.type.quals
        if array_parameter and isinstance(decl.type, c_ast.ArrayDecl):
            return "restrict" not in decl.type.dim_quals
        return self._is_pointer_decl(decl)

    def visit_FuncDef(self, node):
        previous = self.unsafe_pointer_names
        params = node.decl.type.args
        # Pointer variables and array parameters can alias other storage. Fixed
        # local arrays are distinct objects and remain eligible.
        self.unsafe_pointer_names = set(previous)
        owner = self
        class Pointers(c_ast.NodeVisitor):
            def visit_Decl(self, decl):
                if owner._is_pointer_decl(decl):
                    self.all_names.add(decl.name)
                if owner._unsafe_pointer_decl(decl):
                    self.names.add(decl.name)
        pointers = Pointers()
        pointers.names = self.unsafe_pointer_names
        pointers.all_names = self.pointer_names
        pointers.visit(node.body)
        if params:
            class ArrayParameters(c_ast.NodeVisitor):
                def visit_Decl(self, decl):
                    if owner._unsafe_pointer_decl(decl, array_parameter=True):
                        pointers.names.add(decl.name)
                    if isinstance(decl.type, c_ast.ArrayDecl) or owner._is_pointer_decl(decl):
                        pointers.all_names.add(decl.name)
            ArrayParameters().visit(params)
        self.generic_visit(node.body)
        self.unsafe_pointer_names = previous

    def visit_For(self, node):
        line, column = self._location(node)
        try:
            iv, *_ = _loop_header(node, self.type_categories)
        except ValueError:
            iv = None

        nested = _single_nested_for(node.stmt)
        if iv is not None and nested is not None:
            # A perfect counted-loop nest is represented by its innermost loop
            # for SIMD analysis. Outer induction variables remain invariant
            # symbols in the inner loop's affine accesses.
            self.loop_stack.append(iv)
            try:
                self.visit(nested)
            finally:
                self.loop_stack.pop()
            return

        try:
            iv, start, trip_count, step, start_expression, start_names = _loop_header(
                node, self.type_categories
            )
            rebase = _IndexRebase(
                start, step, start_expression, frozenset(start_names)
            )
            statements, reductions, extra_reads, condition_scalars = _body_statements(node.stmt, iv)
            statements = [
                Statement(
                    _rebase_ref(stmt.target, rebase),
                    _rebase_expr(stmt.value, rebase),
                )
                for stmt in statements
            ]
            extra_reads = [
                _rebase_ref(ref, rebase)
                for ref in extra_reads
            ]
            memory_accesses: list[tuple[str, str, str, Ref]] = []
            for stmt in statements:
                target_root = re.match(r"[A-Za-z_]\w*", stmt.target.array).group(0)
                memory_accesses.append((target_root, stmt.target.array, "write", stmt.target))
                memory_accesses.extend(
                    (re.match(r"[A-Za-z_]\w*", ref.array).group(0), ref.array, "read", ref)
                    for ref in stmt.reads()
                )
            memory_accesses.extend(
                (re.match(r"[A-Za-z_]\w*", ref.array).group(0), ref.array, "read", ref)
                for ref in extra_reads
            )
            for position, (first, first_array, first_role, first_ref) in enumerate(memory_accesses):
                for second, second_array, second_role, second_ref in memory_accesses[position + 1:]:
                    if first == second or (first_role == second_role == "read"):
                        if first == second and first_array != second_array and (
                            first_role == "write" or second_role == "write"
                        ):
                            raise ValueError(
                                "outer indexes of the same multidimensional array must match "
                                "within a vectorized loop"
                            )
                        if (first_array == second_array and
                                first_ref.symbolic_offset != second_ref.symbolic_offset):
                            raise ValueError(
                                "symbolic offsets for accesses to the same array must match"
                            )
                        continue
                    if first in self.unsafe_pointer_names or second in self.unsafe_pointer_names:
                        raise ValueError(
                            "potential pointer alias between distinct memory bases; "
                            "use restrict or keep accesses on one pointer base"
                        )
            reduction_names = {name for name, _ in reductions}
            if any(ref.symbolic_names & reduction_names
                   for _, _, _, ref in memory_accesses):
                raise ValueError("a reduction variable cannot appear in an array index")
            loop_indices = set(self.loop_stack) | {iv}
            for _, _, _, ref in memory_accesses:
                if ref.index is None:
                    raise ValueError("array accesses must have affine indexes")
                unsigned_names = {
                    name for name in ref.index_names
                    if self.type_categories.get(name) == "unsigned"
                }
                unknown_names = {
                    name for name in ref.index_names
                    if self.type_categories.get(name) not in ("signed", "unsigned")
                }
                if unknown_names:
                    raise ValueError("array indexes must use supported integer variables")
                if unsigned_names - loop_indices:
                    raise ValueError(
                        "unsigned scalar offsets are unsupported; unsigned loop indexes "
                        "must be induction variables in this loop nest"
                    )
            if any("[" in array and root in self.pointer_names
                   for root, array, _, _ in memory_accesses):
                raise ValueError(
                    "multidimensional pointer accesses may alias between rows"
                )
            dynamic_trip = trip_count is None
            # Unknown trip counts use a conservative upper bound for dependence
            # checks. The C source itself retains its runtime loop condition.
            trip = (1 << 128) if dynamic_trip else trip_count
            calls = {call.name for stmt in statements for call in stmt.calls()}
            pure_calls = calls & (PURE_MATH_CALLS | self.pure_functions.keys())
            if any(self.type_categories.get(name) not in ("signed", "unsigned", "floating")
                   for name, _ in reductions):
                raise ValueError("reduction variables must have supported arithmetic types")
            if any(self.type_categories.get(name) == "volatile" for name in condition_scalars):
                raise ValueError("volatile scalar reads in branch conditions are unsupported")
            if any(self.type_categories.get(scalar.name) == "volatile"
                   for stmt in statements for scalar in stmt.value.scalars()):
                raise ValueError("volatile scalar reads in vectorized loop bodies are unsupported")
            if any(self.type_categories.get(root) == "volatile"
                   for root, _, _, _ in memory_accesses):
                raise ValueError("volatile memory accesses cannot be vectorized")
            loop = Loop(iv=iv, start=start or 0, trip=trip, statements=statements,
                        source=f"line {line}", extra_reads=extra_reads,
                        reductions=reductions, source_level=True,
                        pure_calls=pure_calls)
            self.found.append(CLoop(loop, line, dynamic_trip=dynamic_trip,
                                    reductions=reductions,
                                    declare_simd=[(name, *self.pure_functions[name])
                                                  for name in calls & self.pure_functions.keys()],
                                    column=column))
        except (ValueError, ParseError) as exc:
            self.found.append(CLoop(None, line, str(exc)))
        if iv is None:
            self.generic_visit(node.stmt)
        else:
            self.loop_stack.append(iv)
            try:
                self.generic_visit(node.stmt)
            finally:
                self.loop_stack.pop()

    def visit_While(self, node):
        line, _ = self._location(node)
        self.found.append(CLoop(None, line, "while loops are not supported yet"))
        self.generic_visit(node.stmt)

    def visit_DoWhile(self, node):
        line, _ = self._location(node)
        self.found.append(CLoop(None, line, "do-while loops are not supported yet"))
        self.generic_visit(node.stmt)


def parse_c_text(text: str, source: str = "<memory>") -> list[CLoop]:
    """Parse C and return each counted-for-loop candidate with a reason if unsupported."""
    try:
        prepared, line_offset, column_maps = _prepare_source(text)
        ast = c_parser.CParser().parse(prepared, filename=source)
    except Exception as exc:
        raise ParseError(f"C parse failed: {exc}") from exc
    pure_functions: dict[str, tuple[int, int]] = {}
    for external in ast.ext:
        if not isinstance(external, c_ast.FuncDef):
            continue
        function = external.decl
        if not isinstance(function.type, c_ast.FuncDecl):
            continue
        if isinstance(function.type.type, c_ast.PtrDecl):
            continue
        params = function.type.args.params if function.type.args else []
        param_names = {param.name for param in params if isinstance(param, c_ast.Decl)}
        body = external.body.block_items or []
        if len(body) != 1 or not isinstance(body[0], c_ast.Return) or body[0].expr is None:
            continue
        def pure_expr(node) -> bool:
            if isinstance(node, c_ast.Constant):
                return True
            if isinstance(node, c_ast.ID):
                return node.name in param_names
            if isinstance(node, c_ast.BinaryOp):
                return node.op in C_BINARY_OPS and pure_expr(node.left) and pure_expr(node.right)
            if isinstance(node, c_ast.UnaryOp):
                return node.op in ("-", "+", "!", "~") and pure_expr(node.expr)
            if isinstance(node, c_ast.Cast):
                return pure_expr(node.expr)
            if isinstance(node, c_ast.FuncCall):
                return (isinstance(node.name, c_ast.ID)
                        and node.name.name in PURE_MATH_CALLS
                        and (node.args is None or all(pure_expr(arg) for arg in node.args.exprs)))
            return False
        if pure_expr(body[0].expr):
            line, column = _original_location(
                external.coord, line_offset, column_maps
            )
            pure_functions[function.name] = _declaration_start(text, line, column)

    visitor = _Loops(line_offset, pure_functions, _type_categories(ast), column_maps)
    class PointerAliases(c_ast.NodeVisitor):
        def visit_Typedef(self, node):
            if isinstance(node.type, (c_ast.PtrDecl, c_ast.ArrayDecl)):
                visitor.pointer_typedefs.add(node.name)
    PointerAliases().visit(ast)
    for external in ast.ext:
        if isinstance(external, c_ast.Decl):
            if visitor._is_pointer_decl(external):
                visitor.pointer_names.add(external.name)
            if visitor._unsafe_pointer_decl(external):
                visitor.unsafe_pointer_names.add(external.name)
    visitor.visit(ast)
    return visitor.found


def parse_c_file(path: str | Path) -> list[CLoop]:
    path = Path(path)
    return parse_c_text(path.read_text(encoding="utf-8"), str(path))
