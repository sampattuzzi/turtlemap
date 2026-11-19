from collections.abc import Callable

from tree_sitter import Node as Syntax
from turtlemap.analysis import model as m
from turtlemap.languages.javascript import nodes as ts
from turtlemap.languages.javascript import naming
from turtlemap.languages.javascript import literals
from turtlemap.languages.javascript.lowering.state import LoweringState
from turtlemap.languages.javascript.lowering.ports import (
    ClassesPort,
    CompositesPort,
    FunctionsPort,
    JsxPort,
    OperatorsPort,
)

_Handler = Callable[[Syntax, str | None], m.Expr]
_Spanned = Callable[[Syntax, int, int], m.Expr]


class Expressions:
    classes: ClassesPort
    composites: CompositesPort
    functions: FunctionsPort
    jsx: JsxPort
    operators: OperatorsPort

    def __init__(self, state: LoweringState) -> None:
        self.state = state
        self._handlers = {**self._value_handlers(), **self._operation_handlers()}

    def expr(self, node: Syntax, context: str | None = None) -> m.Expr:
        node = ts.unwrap(node)
        handler = self._handlers.get(node.type)
        if handler is not None:
            return handler(node, context)
        line, end = ts.span(node)
        return m.OtherExpr(
            line,
            end,
            [self.expr(child) for child in ts.named(node) if ts.is_expression(child)],
            origin=node,
        )

    def _value_handlers(self) -> dict[str, _Handler]:
        identifier = _spanned(self._from_identifier)
        return {
            "identifier": identifier,
            "shorthand_property_identifier": identifier,
            "property_identifier": identifier,
            "this": _name("this"),
            "super": _name("super"),
            "null": _constant(None),
            "undefined": _constant(None),
            "true": _constant(True),
            "false": _constant(False),
            "number": _spanned(self._from_number),
            "string": lambda node, context: m.Literal(
                *ts.span(node), literals.string_value(node), origin=node
            ),
            "template_string": lambda node, context: self.composites.template(node),
            "array": lambda node, context: self._from_array(
                node, *ts.span(node), context
            ),
            "object": lambda node, context: self.composites.object(node, context),
            "member_expression": _spanned(self._from_member_expression),
            "subscript_expression": _spanned(self._from_subscript_expression),
            "call_expression": lambda node, context: self.composites.call(node),
            "new_expression": _spanned(self._from_new_expression),
            "regex": lambda node, context: m.OtherExpr(*ts.span(node), [], origin=node),
        }

    def _operation_handlers(self) -> dict[str, _Handler]:
        augmented: _Handler = lambda node, context: self.operators.augmented(node)
        jsx: _Handler = lambda node, context: self.jsx.jsx(node)
        function: _Handler = lambda node, context: self.functions.function_value(
            node, context
        )
        return {
            "await_expression": _spanned(self._from_await_expression),
            "yield_expression": _spanned(self._from_yield_expression),
            "binary_expression": lambda node, context: self.operators.binary(node),
            "unary_expression": lambda node, context: self.operators.unary(node),
            "ternary_expression": lambda node, context: self.operators.ternary(
                node, context
            ),
            **{kind: function for kind in ts.FUNCTIONS},
            "assignment_expression": lambda node, context: self.operators.assignment(
                node
            ),
            "augmented_assignment_expression": augmented,
            "update_expression": augmented,
            "spread_element": _spanned(self._from_spread_element),
            "jsx_element": jsx,
            "jsx_self_closing_element": jsx,
            "jsx_fragment": _spanned(self._from_jsx_fragment),
            "class": lambda node, context: self._from_class(
                node, *ts.span(node), context
            ),
            "sequence_expression": _spanned(self._from_sequence_expression),
        }

    def _from_identifier(self, node: Syntax, line: int, end: int) -> m.Expr:
        text = ts.decode(node.text)
        if text == "undefined":
            return m.Literal(line, end, None, origin=node)
        return m.Name(line, end, text, origin=node)

    def _from_number(self, node: Syntax, line: int, end: int) -> m.Expr:
        return m.Literal(line, end, literals.number(ts.decode(node.text)), origin=node)

    def _from_array(
        self, node: Syntax, line: int, end: int, context: str | None
    ) -> m.Expr:
        return m.Sequence(
            line,
            end,
            "array",
            [self.expr(child, context) for child in ts.named(node)],
            origin=node,
        )

    def _from_member_expression(self, node: Syntax, line: int, end: int) -> m.Expr:
        property_node = ts.field(node, "property")
        return m.Member(
            line,
            end,
            self.expr(ts.field(node, "object")),
            ts.decode(property_node.text),
            origin=node,
        )

    def _from_subscript_expression(self, node: Syntax, line: int, end: int) -> m.Expr:
        return m.Subscript(
            line,
            end,
            self.expr(ts.field(node, "object")),
            self.expr(ts.field(node, "index")),
            origin=node,
        )

    def _from_new_expression(self, node: Syntax, line: int, end: int) -> m.Expr:
        constructor = ts.field(node, "constructor")
        arguments = node.child_by_field_name("arguments")
        return m.Call(
            line,
            end,
            self.expr(constructor),
            (
                self.composites.arguments(arguments, naming.callee_name(constructor))
                if arguments is not None
                else []
            ),
            construct=True,
            origin=node,
        )

    def _from_await_expression(self, node: Syntax, line: int, end: int) -> m.Expr:
        inner = ts.first(node)
        return m.Await(
            line,
            end,
            self.expr(inner) if inner is not None else ts.missing(node),
            origin=node,
        )

    def _from_yield_expression(self, node: Syntax, line: int, end: int) -> m.Expr:
        inner = ts.first(node)
        return m.Yield(
            line,
            end,
            self.expr(inner) if inner is not None else None,
            ts.has_token(node, "*"),
            origin=node,
        )

    def _from_spread_element(self, node: Syntax, line: int, end: int) -> m.Expr:
        inner = ts.first(node)
        return m.Spread(
            line,
            end,
            self.expr(inner) if inner is not None else ts.missing(node),
            origin=node,
        )

    def _from_jsx_fragment(self, node: Syntax, line: int, end: int) -> m.Expr:
        return m.Call(
            line,
            end,
            m.Name(line, end, "<>", origin="<>"),
            self.jsx.jsx_children(node),
            origin=node,
        )

    def _from_class(
        self, node: Syntax, line: int, end: int, context: str | None
    ) -> m.Expr:
        name = self.unique(context or "class")
        self.state.hoisted.append(self.classes.class_def(node, name))
        return m.Name(line, end, name, origin=name)

    def _from_sequence_expression(self, node: Syntax, line: int, end: int) -> m.Expr:
        return m.OtherExpr(
            line, end, [self.expr(child) for child in ts.named(node)], origin=node
        )

    def unique(self, name: str) -> str:
        taken = self.state.scopes[-1]
        candidate = name
        counter = 2
        while candidate in taken:
            candidate = f"{name} {counter}"
            counter += 1
        taken.add(candidate)
        return candidate


def _spanned(lower: _Spanned) -> _Handler:
    return lambda node, context: lower(node, *ts.span(node))


def _constant(value: str | bool | None) -> _Handler:
    return lambda node, context: m.Literal(*ts.span(node), value, origin=node)


def _name(text: str) -> _Handler:
    return lambda node, context: m.Name(*ts.span(node), text, origin=node)
