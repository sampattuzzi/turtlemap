import ast
from typing import Any

from code_blueprints.analysis.workspace import ParsedFunction, ParsedModule


def module_outline(module: ParsedModule) -> list[dict[str, Any]]:
    lines = module.lines
    out: list[dict[str, Any]] = []
    group: dict[str, Any] | None = None
    body = module.tree.body
    for index, node in enumerate(body):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if group is not None:
                group["count"] += 1
                continue
            group = {
                "kind": "imports",
                "no": node.lineno,
                "text": _line(lines, node.lineno),
                "count": 1,
            }
            out.append(group)
            continue
        group = None
        if index == 0 and _is_docstring(node):
            out.append(_doc(node, lines))
            continue
        out.append(_item(node, lines))
    return out


def function_code(module: ParsedModule, function: ParsedFunction) -> list[list[Any]]:
    node = function.node
    lines = module.lines
    start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
    docstring = node.body[0] if node.body and _is_docstring(node.body[0]) else None
    skip = (
        range(docstring.lineno, (docstring.end_lineno or docstring.lineno) + 1)
        if docstring is not None
        else range(0)
    )
    rows: list[list[Any]] = []
    for number in range(start, (node.end_lineno or node.lineno) + 1):
        if number in skip:
            continue
        text = _line(lines, number)
        if not text.strip() or text.strip().startswith("#"):
            continue
        rows.append([number, text])
    return rows


def _item(node: ast.stmt, lines: list[str]) -> dict[str, Any]:
    decorators = [
        [d.lineno, _line(lines, d.lineno)] for d in getattr(node, "decorator_list", [])
    ]
    end = node.end_lineno or node.lineno
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return {
            "kind": "def",
            "name": node.name,
            "no": node.lineno,
            "text": _line(lines, node.lineno),
            "decorators": decorators,
            "end": end,
        }
    if isinstance(node, ast.ClassDef):
        body: list[dict[str, Any]] = []
        for index, child in enumerate(node.body):
            body.append(
                _doc(child, lines)
                if index == 0 and _is_docstring(child)
                else _item(child, lines)
            )
        return {
            "kind": "class",
            "name": node.name,
            "no": node.lineno,
            "text": _line(lines, node.lineno),
            "decorators": decorators,
            "body": body,
            "end": end,
        }
    return {
        "kind": "stmt",
        "no": node.lineno,
        "text": _line(lines, node.lineno),
        "multi": end > node.lineno,
    }


def _doc(node: ast.stmt, lines: list[str]) -> dict[str, Any]:
    return {
        "kind": "doc",
        "no": node.lineno,
        "text": _line(lines, node.lineno),
        "multi": (node.end_lineno or node.lineno) > node.lineno,
    }


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _line(lines: list[str], number: int) -> str:
    return lines[number - 1] if 0 < number <= len(lines) else ""
