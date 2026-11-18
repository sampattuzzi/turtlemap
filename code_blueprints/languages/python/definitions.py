import ast
from collections.abc import Callable, Sequence

from code_blueprints.analysis import model as m
from code_blueprints.languages.python.expressions import ExpressionLowering
from code_blueprints.languages.python.nodes import span

_STATIC_DECORATORS = frozenset({"staticmethod"})
_CLASS_DECORATORS = frozenset({"classmethod"})
_PROPERTY_DECORATORS = frozenset({"property", "cached_property"})


class DefinitionLowering:
    def __init__(
        self,
        expressions: ExpressionLowering,
        block: Callable[[Sequence[ast.stmt]], list[m.Stmt]],
    ) -> None:
        self.expressions = expressions
        self.block = block

    def function_def(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, line: int, end: int
    ) -> m.Stmt:
        return m.FunctionDef(line, end, self.function(node), origin=node)

    def class_def(self, node: ast.ClassDef, line: int, end: int) -> m.Stmt:
        return m.ClassDef(line, end, self.cls(node), origin=node)

    def function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> m.FunctionDecl:
        line, end = span(node)
        decorators = [
            self.expressions.expr(decorator) for decorator in node.decorator_list
        ]
        names = {
            (m.dotted_name(_decorated(decorator)) or "").rsplit(".", 1)[-1]
            for decorator in decorators
        }
        return m.FunctionDecl(
            line,
            end,
            node.name,
            self.expressions.signatures.parameters(node.args),
            (
                self.expressions.signatures.type_expr(node.returns)
                if node.returns is not None
                else None
            ),
            self.block(node.body),
            decorators=decorators,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            doc=ast.get_docstring(node),
            doc_lines=doc_lines(node.body),
            start_line=min([line] + [d.lineno for d in node.decorator_list]),
            binding=_binding(names),
            is_property=bool(names & _PROPERTY_DECORATORS),
            is_overload=any(
                m.dotted_name(decorator) in ("overload", "typing.overload")
                for decorator in decorators
            ),
            is_constructor=node.name == "__init__",
            origin=node,
        )

    def cls(self, node: ast.ClassDef) -> m.ClassDecl:
        line, end = span(node)
        return m.ClassDecl(
            line,
            end,
            node.name,
            [self.expressions.expr(base) for base in node.bases],
            self.block(node.body),
            decorators=[
                self.expressions.expr(decorator) for decorator in node.decorator_list
            ],
            doc=ast.get_docstring(node),
            doc_lines=doc_lines(node.body),
            start_line=min([line] + [d.lineno for d in node.decorator_list]),
            origin=node,
        )


def _binding(names: set[str]) -> str:
    if names & _STATIC_DECORATORS:
        return "static"
    return "class" if names & _CLASS_DECORATORS else "instance"


def _decorated(decorator: m.Expr) -> m.Expr:
    return decorator.func if isinstance(decorator, m.Call) else decorator


def doc_lines(body: Sequence[ast.stmt]) -> tuple[int, int] | None:
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return span(body[0])
    return None
