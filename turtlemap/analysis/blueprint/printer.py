import json

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.code_shapes import is_literal_expression
from turtlemap.analysis.blueprint.text import LITERAL_LIMIT, shorten
from turtlemap.languages.language import Language


class Printer:
    def __init__(self, language: Language) -> None:
        self._language = language
        self._syntax = language.syntax
        self._names: dict[m.Node, str] = {}

    def lines(
        self, expression: m.Expr, leaves: dict[m.Node, str], width: int
    ) -> list[str]:
        self._names = dict(leaves)
        for node in m.walk(expression):
            if (
                isinstance(node, m.Literal)
                and isinstance(node.value, str)
                and len(node.value) > LITERAL_LIMIT
            ):
                self._names.setdefault(
                    node,
                    shorten(json.dumps(node.value, ensure_ascii=False), LITERAL_LIMIT),
                )
        return self._lines(expression, width)

    def _lines(self, expression: m.Expr, width: int) -> list[str]:
        named = self._names.get(expression)
        if named is not None:
            return [named]
        text = self._text(expression)
        if len(text) <= width:
            return [text]
        if isinstance(expression, m.Call):
            return self._call_lines(expression, width)
        if isinstance(expression, m.Sequence):
            return self._collection_lines(expression, width)
        if isinstance(expression, m.Unary):
            prefix = self._unary_prefix(expression)
            inner = self._lines(expression.operand, max(16, width - len(prefix)))
            if self._precedence(expression.operand) < self._precedence(expression):
                inner = _parenthesised(inner)
            return [
                prefix + inner[0],
                *(" " * len(prefix) + line for line in inner[1:]),
            ]
        pieces = self._pieces(expression)
        if pieces is None:
            return [text]
        lines: list[str] = []
        for prefix, piece, minimum in pieces:
            inner = self._lines(piece, max(16, width - len(prefix) - 1))
            if self._precedence(piece) < minimum:
                inner = _parenthesised(inner)
            lines.append(prefix + inner[0])
            lines += [" " * len(prefix) + line for line in inner[1:]]
        return lines

    def _call_lines(self, call: m.Call, width: int) -> list[str]:
        lines = [f"{self._text(call.func)}("]
        arguments = [("", argument) for argument in call.args] + [
            (self._keyword_prefix(keyword), keyword.value) for keyword in call.keywords
        ]
        for prefix, argument in arguments:
            inner = self._lines(argument, max(16, width - 4 - len(prefix)))
            lines.append(f"    {prefix}{inner[0]}")
            lines += [f"    {' ' * len(prefix)}{line}" for line in inner[1:]]
            lines[-1] += ","
        lines.append(")")
        return lines

    def _collection_lines(self, collection: m.Sequence, width: int) -> list[str]:
        opening, closing = self._syntax.brackets.get(collection.kind, ("(", ")"))
        lines = [opening]
        for element in collection.elements:
            inner = self._lines(element, max(16, width - 4))
            lines += [f"    {line}" for line in inner]
            lines[-1] += ","
        lines.append(closing)
        return lines

    def _text(self, expression: m.Expr) -> str:
        named = self._names.get(expression)
        if named is not None:
            return named
        if isinstance(expression, m.Call) and not any(
            isinstance(argument, m.Spread) for argument in expression.args
        ):
            arguments = [self._text(argument) for argument in expression.args] + [
                self._keyword_prefix(keyword) + self._text(keyword.value)
                for keyword in expression.keywords
            ]
            return f"{self._text(expression.func)}({', '.join(arguments)})"
        if isinstance(expression, m.Unary) and not is_literal_expression(expression):
            operand = self._text(expression.operand)
            if self._precedence(expression.operand) < self._precedence(expression):
                operand = f"({operand})"
            return self._unary_prefix(expression) + operand
        pieces = self._pieces(expression)
        if pieces is None:
            if not self._names:
                return self._language.text(expression)
            return self._language.text_with(expression, self._names)
        return " ".join(
            prefix
            + (
                f"({self._text(piece)})"
                if self._precedence(piece) < minimum
                else self._text(piece)
            )
            for prefix, piece, minimum in pieces
        )

    def _keyword_prefix(self, keyword: m.Keyword) -> str:
        if keyword.arg is None:
            return self._language.profile.mapping_spread_prefix
        return f"{keyword.arg}{self._syntax.keyword_separator}"

    def _pieces(self, expression: m.Expr) -> list[tuple[str, m.Expr, int]] | None:
        operators = self._syntax.operators
        if isinstance(expression, m.Logical):
            word, level = operators[expression.op]
            return [
                ("" if index == 0 else f"{word} ", value, level + 1)
                for index, value in enumerate(expression.values)
            ]
        if (
            isinstance(expression, m.Binary)
            and expression.op not in self._syntax.unchained_operators
        ):
            level = self._precedence(expression)
            terms: list[tuple[str, m.Expr]] = []
            current: m.Expr = expression
            while (
                isinstance(current, m.Binary)
                and current not in self._names
                and self._precedence(current) == level
            ):
                terms.append((f"{operators[current.op][0]} ", current.right))
                current = current.left
            terms.reverse()
            return [("", current, level)] + [
                (prefix, term, level + 1) for prefix, term in terms
            ]
        if isinstance(expression, m.Conditional):
            if self._syntax.conditional_first:
                return [
                    ("", expression.test, 1),
                    ("? ", expression.body, 0),
                    (": ", expression.orelse, 0),
                ]
            return [
                ("", expression.body, 1),
                ("if ", expression.test, 1),
                ("else ", expression.orelse, 0),
            ]
        if isinstance(expression, m.Compare):
            level = self._syntax.compare_precedence + 1
            return [("", expression.left, level)] + [
                (f"{self._syntax.comparisons.get(op, op)} ", comparator, level)
                for op, comparator in zip(expression.ops, expression.comparators)
            ]
        return None

    def _unary_prefix(self, expression: m.Unary) -> str:
        return self._syntax.unary_prefixes.get(expression.op, expression.op)

    def _precedence(self, expression: m.Expr) -> int:
        if expression in self._names:
            return 13
        if isinstance(expression, (m.Logical, m.Binary)):
            return self._syntax.operators[expression.op][1]
        if isinstance(expression, m.Compare):
            return self._syntax.compare_precedence
        if isinstance(expression, m.Unary):
            return self._syntax.unary_precedence.get(expression.op, 11)
        if isinstance(expression, (m.Conditional, m.Function, m.AssignExpr)):
            return 0
        return 13


def _parenthesised(lines: list[str]) -> list[str]:
    if len(lines) == 1:
        return [f"({lines[0]})"]
    return [f"({lines[0]}", *(f" {line}" for line in lines[1:-1]), f" {lines[-1]})"]
