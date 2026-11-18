import ast
from code_blueprints.analysis import model as m
from collections.abc import Callable

BINARY: dict[type[ast.operator], str] = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.Mod: "%",
    ast.Pow: "**",
    ast.MatMult: "@",
    ast.LShift: "<<",
    ast.RShift: ">>",
    ast.BitOr: "|",
    ast.BitAnd: "&",
    ast.BitXor: "^",
}
_COMPARE: dict[type[ast.cmpop], str] = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Is: "is",
    ast.IsNot: "is not",
    ast.In: "in",
    ast.NotIn: "not in",
}
_UNARY: dict[type[ast.unaryop], str] = {
    ast.Not: "not",
    ast.USub: "-",
    ast.UAdd: "+",
    ast.Invert: "~",
}


class OperatorLowering:
    def __init__(self, expr: Callable[[ast.expr], m.Expr]) -> None:
        self.expr = expr

    def bin_op(self, node: ast.BinOp, line: int, end: int) -> m.Expr:
        return m.Binary(
            line,
            end,
            BINARY.get(type(node.op), "?"),
            self.expr(node.left),
            self.expr(node.right),
            origin=node,
        )

    def unary_op(self, node: ast.UnaryOp, line: int, end: int) -> m.Expr:
        return m.Unary(
            line,
            end,
            _UNARY.get(type(node.op), "?"),
            self.expr(node.operand),
            origin=node,
        )

    def compare(self, node: ast.Compare, line: int, end: int) -> m.Expr:
        return m.Compare(
            line,
            end,
            self.expr(node.left),
            [_COMPARE.get(type(op), "?") for op in node.ops],
            [self.expr(comparator) for comparator in node.comparators],
            origin=node,
        )

    def bool_op(self, node: ast.BoolOp, line: int, end: int) -> m.Expr:
        return m.Logical(
            line,
            end,
            "and" if isinstance(node.op, ast.And) else "or",
            [self.expr(value) for value in node.values],
            origin=node,
        )
