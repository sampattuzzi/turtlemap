import ast
from turtlemap.analysis import model as m
from collections.abc import Callable

from turtlemap.languages.python.nodes import span

_COMPREHENSION_KINDS: dict[type[ast.expr], str] = {
    ast.ListComp: "list",
    ast.SetComp: "set",
    ast.DictComp: "dict",
    ast.GeneratorExp: "generator",
}

_SEQUENCE_KINDS: dict[type[ast.expr], str] = {
    ast.Tuple: "tuple",
    ast.List: "list",
    ast.Set: "set",
}


class DisplayLowering:
    def __init__(
        self,
        expr: Callable[[ast.expr], m.Expr],
        optional: Callable[[ast.expr | None], m.Expr | None],
    ) -> None:
        self.expr = expr
        self.optional = optional

    def sequence(
        self, node: ast.Tuple | ast.List | ast.Set, line: int, end: int
    ) -> m.Expr:
        return m.Sequence(
            line,
            end,
            _SEQUENCE_KINDS[type(node)],
            [self.expr(element) for element in node.elts],
            isinstance(getattr(node, "ctx", None), ast.Store),
            origin=node,
        )

    def mapping(self, node: ast.Dict, line: int, end: int) -> m.Expr:
        return m.Mapping(
            line,
            end,
            [self.expr(key) if key is not None else None for key in node.keys],
            [self.expr(value) for value in node.values],
            origin=node,
        )

    def joined_str(self, node: ast.JoinedStr, line: int, end: int) -> m.Expr:
        return m.Template(
            line, end, [self.expr(part) for part in node.values], origin=node
        )

    def formatted_value(self, node: ast.FormattedValue, line: int, end: int) -> m.Expr:
        return m.Interpolation(
            line,
            end,
            self.expr(node.value),
            self.optional(node.format_spec),
            origin=node,
        )

    def comprehension(self, node: ast.expr) -> m.Expr:
        line, end = span(node)
        results: list[m.Expr]
        if isinstance(node, ast.DictComp):
            results = [self.expr(node.key), self.expr(node.value)]
        else:
            assert isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp))
            results = [self.expr(node.elt)]
        generators = node.generators
        clauses = [
            m.ComprehensionClause(
                *span(generator.iter),
                self.expr(generator.target),
                self.expr(generator.iter),
                [self.expr(condition) for condition in generator.ifs],
                bool(generator.is_async),
                origin=generator,
            )
            for generator in generators
        ]
        bound = [
            child.id
            for generator in generators
            for child in ast.walk(generator.target)
            if isinstance(child, ast.Name)
        ]
        return m.Comprehension(
            line,
            end,
            _COMPREHENSION_KINDS[type(node)],
            results,
            clauses,
            bound,
            origin=node,
        )
