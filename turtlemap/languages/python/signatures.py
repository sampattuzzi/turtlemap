import ast
from collections.abc import Callable

from turtlemap.analysis import model as m
from turtlemap.languages.python.nodes import span


class SignatureLowering:
    def __init__(
        self,
        expr: Callable[[ast.expr], m.Expr],
        optional: Callable[[ast.expr | None], m.Expr | None],
    ) -> None:
        self.expr = expr
        self.optional = optional

    def type_expr(self, node: ast.expr) -> m.TypeExpr:
        line, end = span(node)
        if isinstance(node, ast.Constant):
            parsed: m.TypeExpr | None = None
            if isinstance(node.value, str):
                try:
                    parsed = self.type_expr(ast.parse(node.value, mode="eval").body)
                except SyntaxError:
                    parsed = None
            return m.TypeLiteral(line, end, node.value, parsed, origin=node)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return m.TypeUnion(
                line,
                end,
                [self.type_expr(member) for member in _flatten_union(node)],
                origin=node,
            )
        if isinstance(node, (ast.Name, ast.Attribute)):
            dotted = _dotted(node)
            if dotted is None:
                return m.TypeOther(line, end, "Any", origin=node)
            return m.TypeName(line, end, dotted, origin=node)
        if isinstance(node, ast.Subscript):
            args = (
                list(node.slice.elts)
                if isinstance(node.slice, ast.Tuple)
                else [node.slice]
            )
            return m.TypeName(
                line,
                end,
                _dotted(node.value) or "",
                [self.type_expr(argument) for argument in args],
                origin=node,
            )
        return m.TypeOther(line, end, value=self.expr(node), origin=node)

    def parameters(self, arguments: ast.arguments) -> list[m.Parameter]:
        positional = [*arguments.posonlyargs, *arguments.args]
        defaults: list[ast.expr | None] = [None] * (
            len(positional) - len(arguments.defaults)
        ) + list(arguments.defaults)
        out = [
            self.parameter(
                argument,
                default,
                (
                    "positional_only"
                    if index < len(arguments.posonlyargs)
                    else "positional"
                ),
            )
            for index, (argument, default) in enumerate(zip(positional, defaults))
        ]
        if arguments.vararg is not None:
            out.append(self.parameter(arguments.vararg, None, "variadic"))
        out += [
            self.parameter(argument, default, "keyword_only")
            for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults)
        ]
        if arguments.kwarg is not None:
            out.append(self.parameter(arguments.kwarg, None, "variadic_keyword"))
        return out

    def parameter(
        self, argument: ast.arg, default: ast.expr | None, kind: str
    ) -> m.Parameter:
        return m.Parameter(
            *span(argument),
            argument.arg,
            (
                self.type_expr(argument.annotation)
                if argument.annotation is not None
                else None
            ),
            self.optional(default),
            kind,
            origin=argument,
        )


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base is not None else None
    return None


def _flatten_union(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _flatten_union(node.left) + _flatten_union(node.right)
    return [node]
