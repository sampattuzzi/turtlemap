from tree_sitter import Node as Syntax

from turtlemap.analysis import model as m
from turtlemap.languages.javascript import naming
from turtlemap.languages.javascript import nodes as ts
from turtlemap.languages.javascript.lowering.ports import (
    ExpressionsPort,
    TargetsPort,
)
from turtlemap.languages.javascript.profile import JAVASCRIPT_SYNTAX

_COMPARISONS = frozenset(JAVASCRIPT_SYNTAX.comparisons)


class Operators:
    expressions: ExpressionsPort
    targets: TargetsPort

    def binary(self, node: Syntax) -> m.Expr:
        line, end = ts.span(node)
        operator = ts.operator(node)
        left = ts.field(node, "left")
        right = ts.field(node, "right")
        if operator in ts.LOGICAL:
            op = ts.LOGICAL[operator]
            values = [*self._chained(left, op), *self._chained(right, op)]
            return m.Logical(line, end, op, values, origin=node)
        if operator in _COMPARISONS:
            return m.Compare(
                line,
                end,
                self.expressions.expr(left),
                [operator],
                [self.expressions.expr(right)],
                origin=node,
            )
        return m.Binary(
            line,
            end,
            operator,
            self.expressions.expr(left),
            self.expressions.expr(right),
            origin=node,
        )

    def unary(self, node: Syntax) -> m.Expr:
        operator = ts.operator(node)
        return m.Unary(
            *ts.span(node),
            ts.UNARY.get(operator, operator),
            self.expressions.expr(ts.field(node, "argument")),
            origin=node,
        )

    def ternary(self, node: Syntax, context: str | None) -> m.Expr:
        return m.Conditional(
            *ts.span(node),
            self.expressions.expr(ts.field(node, "condition")),
            self.expressions.expr(ts.field(node, "consequence"), context),
            self.expressions.expr(ts.field(node, "alternative"), context),
            origin=node,
        )

    def assignment(self, node: Syntax) -> m.Expr:
        line, end = ts.span(node)
        left = ts.unwrap(ts.field(node, "left"))
        value = self.expressions.expr(
            ts.field(node, "right"), naming.last_segment(left)
        )
        if left.type == "identifier":
            target = m.Name(*ts.span(left), ts.decode(left.text), True, origin=left)
            return m.AssignExpr(line, end, target, value, origin=node)
        return m.OtherExpr(line, end, [self.targets.target(left), value], origin=node)

    def augmented(self, node: Syntax) -> m.Expr:
        line, end = ts.span(node)
        if node.type == "update_expression":
            argument = ts.field(node, "argument")
            return m.AugAssignExpr(
                line,
                end,
                self.targets.target(argument),
                "+" if "++" in ts.operator(node) else "-",
                m.Literal(line, end, 1, origin="1"),
                node.children[0] == argument,
                origin=node,
            )
        operator = ts.operator(node).removesuffix("=")
        return m.AugAssignExpr(
            line,
            end,
            self.targets.target(ts.field(node, "left")),
            ts.LOGICAL.get(operator, operator),
            self.expressions.expr(ts.field(node, "right")),
            origin=node,
        )

    def _chained(self, operand: Syntax, op: str) -> list[m.Expr]:
        inner = ts.unwrap(operand)
        lowered = self.expressions.expr(inner)
        if isinstance(lowered, m.Logical) and lowered.op == op and inner is operand:
            return list(lowered.values)
        return [lowered]
