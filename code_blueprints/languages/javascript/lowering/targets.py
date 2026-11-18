from tree_sitter import Node as Syntax

from code_blueprints.analysis import model as m
from code_blueprints.languages.javascript import nodes as ts
from code_blueprints.languages.javascript.lowering.ports import ExpressionsPort

_NAMES = frozenset({"identifier", "shorthand_property_identifier_pattern"})

_PATTERNS = frozenset({"object_pattern", "array_pattern"})

_DEFAULTED = frozenset({"assignment_pattern", "object_assignment_pattern"})

_DECLARATIONS = frozenset({"lexical_declaration", "variable_declaration"})


class Targets:
    expressions: ExpressionsPort

    def target(self, node: Syntax) -> m.Expr:
        node = ts.unwrap(node)
        line, end = ts.span(node)
        kind = node.type
        if kind in _NAMES:
            return m.Name(line, end, ts.decode(node.text), True, origin=node)
        if kind == "member_expression":
            return self._member(node, line, end)
        if kind == "subscript_expression":
            return self._subscript(node, line, end)
        if kind in _PATTERNS:
            return self._pattern(node, line, end)
        if kind == "rest_pattern":
            return self._rest(node, line, end)
        if kind in _DEFAULTED:
            return self.target(ts.field(node, "left"))
        declared = self._declared(node) if kind in _DECLARATIONS else None
        return declared if declared is not None else self.expressions.expr(node)

    def _member(self, node: Syntax, line: int, end: int) -> m.Expr:
        return m.Member(
            line,
            end,
            self.expressions.expr(ts.field(node, "object")),
            ts.decode(ts.field(node, "property").text),
            True,
            origin=node,
        )

    def _subscript(self, node: Syntax, line: int, end: int) -> m.Expr:
        return m.Subscript(
            line,
            end,
            self.expressions.expr(ts.field(node, "object")),
            self.expressions.expr(ts.field(node, "index")),
            True,
            origin=node,
        )

    def _pattern(self, node: Syntax, line: int, end: int) -> m.Expr:
        elements = [self.target(ts.pattern_target(child)) for child in ts.named(node)]
        kind = "object" if node.type == "object_pattern" else "array"
        return m.Sequence(line, end, kind, elements, True, origin=node)

    def _rest(self, node: Syntax, line: int, end: int) -> m.Expr:
        inner = ts.first(node)
        value = (
            self.target(inner) if inner is not None else m.Name(line, end, "rest", True)
        )
        return m.Spread(line, end, value, True, origin=node)

    def _declared(self, node: Syntax) -> m.Expr | None:
        declarator = next(
            (c for c in node.named_children if c.type == "variable_declarator"),
            None,
        )
        if declarator is None:
            return None
        return self.target(ts.field(declarator, "name"))
