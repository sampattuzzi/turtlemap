from collections.abc import Callable

from tree_sitter import Node as Syntax

from turtlemap.analysis import model as m
from turtlemap.languages.javascript import nodes as ts


class TypeAnnotations:
    def __init__(self, expr: Callable[[Syntax], m.Expr]) -> None:
        self._expr = expr
        self._forms: dict[str, Callable[[Syntax], m.TypeExpr]] = {
            **dict.fromkeys(
                ("predefined_type", "type_identifier", "nested_type_identifier"),
                _named,
            ),
            "generic_type": self._generic,
            "array_type": self._array,
            "union_type": self._union,
            **dict.fromkeys(
                ("parenthesized_type", "readonly_type", "type_annotation"),
                self._inner,
            ),
            "literal_type": self._literal,
            "function_type": _shaped("callable"),
            "object_type": _shaped("map"),
            "tuple_type": _shaped("list"),
        }

    def annotation(self, node: Syntax | None) -> m.TypeExpr | None:
        if node is None:
            return None
        if node.type in ("type_annotation", "opting_type_annotation"):
            inner = ts.first(node)
            return self.expression(inner) if inner is not None else None
        return self.expression(node)

    def reference(self, node: Syntax) -> m.Expr:
        line, end = ts.span(node)
        if node.type == "generic_type":
            inner = node.child_by_field_name("name")
            if inner is not None:
                return self.reference(inner)
        dotted = ts.decode(node.text)
        parts = dotted.split(".")
        expression: m.Expr = m.Name(line, end, parts[0], origin=parts[0])
        for index, part in enumerate(parts[1:], start=2):
            expression = m.Member(
                line, end, expression, part, origin=".".join(parts[:index])
            )
        return expression

    def expression(self, node: Syntax) -> m.TypeExpr:
        form = self._forms.get(node.type)
        if form is not None:
            return form(node)
        line, end = ts.span(node)
        return m.TypeOther(line, end, None, origin=node)

    def _generic(self, node: Syntax) -> m.TypeExpr:
        line, end = ts.span(node)
        name = node.child_by_field_name("name")
        arguments = node.child_by_field_name("type_arguments")
        return m.TypeName(
            line,
            end,
            ts.decode(name.text) if name is not None else "",
            [self.expression(a) for a in ts.named(arguments)] if arguments else [],
            origin=node,
        )

    def _array(self, node: Syntax) -> m.TypeExpr:
        line, end = ts.span(node)
        inner = ts.first(node)
        return m.TypeName(
            line,
            end,
            "Array",
            [self.expression(inner)] if inner is not None else [],
            origin=node,
        )

    def _union(self, node: Syntax) -> m.TypeExpr:
        line, end = ts.span(node)
        return m.TypeUnion(
            line,
            end,
            [self.expression(member) for member in ts.union_members(node)],
            origin=node,
        )

    def _inner(self, node: Syntax) -> m.TypeExpr:
        inner = ts.first(node)
        if inner is not None:
            return self.expression(inner)
        line, end = ts.span(node)
        return m.TypeOther(line, end, origin=node)

    def _literal(self, node: Syntax) -> m.TypeExpr:
        line, end = ts.span(node)
        inner = ts.first(node)
        if inner is not None and inner.type in ("null", "undefined"):
            return m.TypeName(line, end, inner.type, origin=node)
        value = self._expr(inner) if inner is not None else None
        return m.TypeLiteral(
            line,
            end,
            value.value if isinstance(value, m.Literal) else None,
            origin=node,
        )


def _named(node: Syntax) -> m.TypeExpr:
    line, end = ts.span(node)
    return m.TypeName(line, end, ts.decode(node.text), origin=node)


def _shaped(shape: str) -> Callable[[Syntax], m.TypeExpr]:
    def build(node: Syntax) -> m.TypeExpr:
        line, end = ts.span(node)
        return m.TypeOther(line, end, None, shape, origin=node)

    return build
