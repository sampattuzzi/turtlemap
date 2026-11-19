from typing import Any

from turtlemap.analysis import model as m
from turtlemap.analysis.workspace.parsed import ParsedFunction, ParsedModule


def module_outline(module: ParsedModule) -> list[dict[str, Any]]:
    lines = module.lines
    out: list[dict[str, Any]] = []
    group: dict[str, Any] | None = None
    last_import = 0
    for index, node in enumerate(_in_order(module.body)):
        if isinstance(node, m.Import):
            if group is not None:
                group["count"] += node.line != last_import
                last_import = node.line
                continue
            group = {
                "kind": "imports",
                "no": node.line,
                "text": _line(lines, node.line),
                "count": 1,
            }
            last_import = node.line
            out.append(group)
            continue
        group = None
        if out and _first_line(node) <= out[-1]["no"]:
            continue
        if index == 0 and _is_docstring(node):
            out.append(_doc(node, lines))
            continue
        out.append(_item(node, lines))
    return out


def function_code(module: ParsedModule, function: ParsedFunction) -> list[list[Any]]:
    node = function.node
    lines = module.lines
    start = node.start_line or node.line
    skip = (
        range(node.doc_lines[0], node.doc_lines[1] + 1)
        if node.doc_lines is not None
        else range(0)
    )
    comment = module.language.comment_prefix
    rows: list[list[Any]] = []
    for number in range(start, (node.end_line or node.line) + 1):
        if number in skip:
            continue
        text = _line(lines, number)
        if not text.strip() or text.strip().startswith(comment):
            continue
        rows.append([number, text])
    return rows


def _item(node: m.Stmt, lines: list[str]) -> dict[str, Any]:
    if isinstance(node, m.FunctionDef):
        function = node.function
        return {
            "kind": "def",
            "name": function.name,
            "no": function.line,
            "text": _line(lines, function.line),
            "decorators": _decorators(function.decorators, lines),
            "end": function.end_line or function.line,
        }
    if isinstance(node, m.ClassDef):
        cls = node.cls
        body: list[dict[str, Any]] = []
        for index, child in enumerate(_in_order(cls.body)):
            if body and _first_line(child) <= body[-1]["no"]:
                continue
            body.append(
                _doc(child, lines)
                if index == 0 and _is_docstring(child)
                else _item(child, lines)
            )
        return {
            "kind": "class",
            "name": cls.name,
            "no": cls.line,
            "text": _line(lines, cls.line),
            "decorators": _decorators(cls.decorators, lines),
            "body": body,
            "end": cls.end_line or cls.line,
        }
    end = node.end_line or node.line
    return {
        "kind": "stmt",
        "no": node.line,
        "text": _line(lines, node.line),
        "multi": end > node.line,
    }


def _in_order(body: list[m.Stmt]) -> list[m.Stmt]:
    return sorted(body, key=_first_line)


def _first_line(node: m.Stmt) -> int:
    if isinstance(node, m.FunctionDef):
        return node.function.line
    if isinstance(node, m.ClassDef):
        return node.cls.line
    return node.line


def _decorators(decorators: list[m.Expr], lines: list[str]) -> list[list[Any]]:
    return [[d.line, _line(lines, d.line)] for d in decorators]


def _doc(node: m.Stmt, lines: list[str]) -> dict[str, Any]:
    return {
        "kind": "doc",
        "no": node.line,
        "text": _line(lines, node.line),
        "multi": (node.end_line or node.line) > node.line,
    }


def _is_docstring(node: m.Stmt) -> bool:
    return (
        isinstance(node, m.ExprStmt)
        and isinstance(node.value, m.Literal)
        and isinstance(node.value.value, str)
    )


def _line(lines: list[str], number: int) -> str:
    return lines[number - 1] if 0 < number <= len(lines) else ""
