from collections.abc import Callable, Sequence

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.canvas import Graph
from turtlemap.analysis.blueprint.lookups import TypeLookups
from turtlemap.analysis.blueprint.syntax import Form, infix
from turtlemap.analysis.blueprint.text import pin_name
from turtlemap.analysis.blueprint.values import BOOL, Value
from turtlemap.analysis.types import UNKNOWN, PinType

_LOGICAL: dict[str, str] = {"and": "AND", "or": "OR", "??": "??"}

_UNARY: dict[str, str] = {"not": "NOT", "-": "-", "+": "+", "~": "~"}

_COMPARISONS: dict[str, str] = {
    "==": "==",
    "!=": "!=",
    "<": "<",
    "<=": "≤",
    ">": ">",
    ">=": "≥",
    "is": "is",
    "is not": "is not",
    "in": "in",
    "not in": "not in",
    "===": "===",
    "!==": "!==",
    "instanceof": "instanceof",
}


class Operations:
    def __init__(
        self,
        lookups: TypeLookups,
        graph: Graph,
        evaluate: Callable[[m.Expr], Value],
        text: Callable[[m.Node], str],
    ) -> None:
        self._lookups = lookups
        self._graph = graph
        self._evaluate = evaluate
        self._text = text

    def logical(self, expression: m.Logical) -> Value:
        values = [self._evaluate(value) for value in expression.values]
        result = (
            BOOL
            if all(value.type.cat == "bool" for value in values)
            else values[0].type
        )
        return self._operation(
            _LOGICAL.get(expression.op, expression.op),
            expression.line,
            _lettered(values),
            result,
            infix(expression.op),
        )

    def binary(self, expression: m.Binary) -> Value:
        left = self._evaluate(expression.left)
        right = self._evaluate(expression.right)
        result = (
            left.type
            if left.type.cat != "any" and left.type.cat == right.type.cat
            else (left.type if left.type.cat == "str" else UNKNOWN)
        )
        return self._operation(
            expression.op,
            expression.line,
            [("a", left), ("b", right)],
            result,
            infix(expression.op),
        )

    def unary(self, expression: m.Unary) -> Value:
        operand = self._evaluate(expression.operand)
        result = BOOL if expression.op == "not" else operand.type
        return self._operation(
            _UNARY.get(expression.op, expression.op),
            expression.line,
            [("value", operand)],
            result,
            Form("prefix", expression.op),
        )

    def compare(self, expression: m.Compare) -> Value:
        if (
            len(expression.ops) == 1
            and expression.ops[0] in ("is", "is not")
            and _is_none(expression.comparators[0])
        ):
            title = "is None" if expression.ops[0] == "is" else "is not None"
            left = self._evaluate(expression.left)
            return self._operation(
                title, expression.line, [("value", left)], BOOL, Form("suffix", title)
            )
        operands = [
            self._evaluate(expression.left),
            *(self._evaluate(comparator) for comparator in expression.comparators),
        ]
        return self._operation(
            _comparison_title(expression.ops),
            expression.line,
            _lettered(operands),
            BOOL,
            infix(*expression.ops),
        )

    def subscript(self, expression: m.Subscript) -> Value:
        container = self._evaluate(expression.value)
        container_name = pin_name(expression.value)
        result = self._lookups.item(container, expression.index)
        key = expression.index
        if isinstance(key, m.Slice):
            inputs = [(container_name, container), *self._slice_parts(key)]
            result = container.type if result is UNKNOWN else result
            return self._operation(
                f"[{self._text(key)}]", expression.line, inputs, result, Form("slice")
            )
        key_value = self._evaluate(key)
        if key_value.literal is not None and len(key_value.literal) <= 20:
            return self._operation(
                f"[{key_value.literal}]",
                expression.line,
                [(container_name, container)],
                result,
                Form("index", f"[{key_value.literal}]"),
            )
        return self._operation(
            "[ ]",
            expression.line,
            [(container_name, container), ("key", key_value)],
            result,
            Form("index"),
        )

    def _slice_parts(self, key: m.Slice) -> list[tuple[str, Value]]:
        parts = (("lower", key.lower), ("upper", key.upper), ("step", key.step))
        return [
            (name, self._evaluate(part)) for name, part in parts if part is not None
        ]

    def _operation(
        self,
        title: str,
        line: int,
        inputs: Sequence[tuple[str, Value]],
        result: PinType,
        form: Form,
    ) -> Value:
        node = self._graph.add("op", title, line)
        node.form = form
        for name, value in inputs:
            self._graph.connect(node, name, value)
        return self._graph.output(node, "", result)


def _comparison_title(ops: Sequence[str]) -> str:
    symbols = [_COMPARISONS.get(op, op) for op in ops]
    if len(symbols) == 1:
        return symbols[0]
    return (
        " ".join(
            part
            for index, symbol in enumerate(symbols)
            for part in (_letter(index), symbol)
        )
        + f" {_letter(len(symbols))}"
    )


def _lettered(values: Sequence[Value]) -> list[tuple[str, Value]]:
    return [(_letter(index), value) for index, value in enumerate(values)]


def _letter(index: int) -> str:
    return chr(ord("a") + index) if index < 26 else f"v{index + 1}"


def _is_none(expression: m.Expr) -> bool:
    return isinstance(expression, m.Literal) and expression.value is None
