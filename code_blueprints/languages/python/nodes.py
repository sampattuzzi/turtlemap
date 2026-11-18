import ast
from collections.abc import Callable
from typing import TypeVar

_Node = TypeVar("_Node", bound=ast.AST)
_Lowered = TypeVar("_Lowered")


def on(
    kind: type[_Node], lower: Callable[[_Node, int, int], _Lowered]
) -> tuple[type[ast.AST], Callable[[ast.AST], _Lowered]]:
    def run(node: ast.AST) -> _Lowered:
        assert isinstance(node, kind)
        return lower(node, *span(node))

    return kind, run


def span(node: ast.AST) -> tuple[int, int]:
    line = int(getattr(node, "lineno", 0) or 0)
    end = getattr(node, "end_lineno", None)
    return line, int(end) if end is not None else line
