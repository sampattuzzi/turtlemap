import ast
from collections.abc import Callable

from code_blueprints.analysis import model as m
from code_blueprints.languages.python.displays import DisplayLowering
from code_blueprints.languages.python.nodes import on, span
from code_blueprints.languages.python.operators import OperatorLowering
from code_blueprints.languages.python.signatures import SignatureLowering

_ExpressionRow = tuple[type[ast.AST], Callable[[ast.AST], m.Expr]]


class ExpressionLowering:
    def __init__(self) -> None:
        self.operators = OperatorLowering(self.expr)
        self.displays = DisplayLowering(self.expr, self.optional)
        self.signatures = SignatureLowering(self.expr, self.optional)
        self._handlers = dict(self._value_handlers() + self._operation_handlers())

    def optional(self, node: ast.expr | None) -> m.Expr | None:
        return self.expr(node) if node is not None else None

    def expr(self, node: ast.expr) -> m.Expr:
        handler = self._handlers.get(type(node))
        if handler is not None:
            return handler(node)
        line, end = span(node)
        return m.OtherExpr(
            line,
            end,
            [
                self.expr(child)
                for child in ast.iter_child_nodes(node)
                if isinstance(child, ast.expr)
            ],
            origin=node,
        )

    def _value_handlers(self) -> list[_ExpressionRow]:
        return [
            on(ast.Name, self._from_name),
            on(ast.Attribute, self._from_attribute),
            on(ast.Call, self._from_call),
            on(ast.Constant, _from_constant),
            on(ast.Tuple, self.displays.sequence),
            on(ast.List, self.displays.sequence),
            on(ast.Set, self.displays.sequence),
            on(ast.Dict, self.displays.mapping),
            on(ast.Subscript, self._from_subscript),
            on(ast.Slice, self._from_slice),
            on(ast.JoinedStr, self.displays.joined_str),
            on(ast.FormattedValue, self.displays.formatted_value),
        ]

    def _operation_handlers(self) -> list[_ExpressionRow]:
        return [
            on(ast.BinOp, self.operators.bin_op),
            on(ast.UnaryOp, self.operators.unary_op),
            on(ast.Compare, self.operators.compare),
            on(ast.BoolOp, self.operators.bool_op),
            on(ast.IfExp, self._from_if_exp),
            on(ast.ListComp, self._from_comprehension),
            on(ast.SetComp, self._from_comprehension),
            on(ast.DictComp, self._from_comprehension),
            on(ast.GeneratorExp, self._from_comprehension),
            on(ast.Lambda, self._from_lambda),
            on(ast.Await, self._from_await),
            on(ast.Yield, self._from_yield),
            on(ast.YieldFrom, self._from_yield_from),
            on(ast.NamedExpr, self._from_named_expr),
            on(ast.Starred, self._from_starred),
        ]

    def _from_comprehension(self, node: ast.expr, line: int, end: int) -> m.Expr:
        return self.displays.comprehension(node)

    def _from_await(self, node: ast.Await, line: int, end: int) -> m.Expr:
        return m.Await(line, end, self.expr(node.value), origin=node)

    def _from_yield(self, node: ast.Yield, line: int, end: int) -> m.Expr:
        return m.Yield(line, end, self.optional(node.value), origin=node)

    def _from_yield_from(self, node: ast.YieldFrom, line: int, end: int) -> m.Expr:
        return m.Yield(line, end, self.expr(node.value), True, origin=node)

    def _from_name(self, node: ast.Name, line: int, end: int) -> m.Expr:
        return m.Name(
            line,
            end,
            node.id,
            isinstance(node.ctx, (ast.Store, ast.Del)),
            origin=node,
        )

    def _from_attribute(self, node: ast.Attribute, line: int, end: int) -> m.Expr:
        return m.Member(
            line,
            end,
            self.expr(node.value),
            node.attr,
            isinstance(node.ctx, ast.Store),
            origin=node,
        )

    def _from_call(self, node: ast.Call, line: int, end: int) -> m.Expr:
        return m.Call(
            line,
            end,
            self.expr(node.func),
            [self.expr(argument) for argument in node.args],
            [
                m.Keyword(
                    *span(keyword.value),
                    keyword.arg,
                    self.expr(keyword.value),
                    origin=keyword,
                )
                for keyword in node.keywords
            ],
            origin=node,
        )

    def _from_subscript(self, node: ast.Subscript, line: int, end: int) -> m.Expr:
        return m.Subscript(
            line,
            end,
            self.expr(node.value),
            self.expr(node.slice),
            isinstance(node.ctx, ast.Store),
            origin=node,
        )

    def _from_slice(self, node: ast.Slice, line: int, end: int) -> m.Expr:
        return m.Slice(
            line,
            end,
            self.optional(node.lower),
            self.optional(node.upper),
            self.optional(node.step),
            origin=node,
        )

    def _from_if_exp(self, node: ast.IfExp, line: int, end: int) -> m.Expr:
        return m.Conditional(
            line,
            end,
            self.expr(node.test),
            self.expr(node.body),
            self.expr(node.orelse),
            origin=node,
        )

    def _from_lambda(self, node: ast.Lambda, line: int, end: int) -> m.Expr:
        return m.Function(
            line,
            end,
            self.signatures.parameters(node.args),
            [],
            self.expr(node.body),
            origin=node,
        )

    def _from_named_expr(self, node: ast.NamedExpr, line: int, end: int) -> m.Expr:
        target = self.expr(node.target)
        assert isinstance(target, m.Name)
        return m.AssignExpr(line, end, target, self.expr(node.value), origin=node)

    def _from_starred(self, node: ast.Starred, line: int, end: int) -> m.Expr:
        return m.Spread(
            line,
            end,
            self.expr(node.value),
            isinstance(node.ctx, ast.Store),
            origin=node,
        )


def _from_constant(node: ast.Constant, line: int, end: int) -> m.Expr:
    return m.Literal(line, end, node.value, origin=node)
