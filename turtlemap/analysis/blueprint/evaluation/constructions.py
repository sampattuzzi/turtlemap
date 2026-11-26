from collections.abc import Callable, Sequence

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.canvas import Graph
from turtlemap.analysis.blueprint.syntax import Form
from turtlemap.analysis.blueprint.text import pin_name, shorten
from turtlemap.analysis.blueprint.values import STR, Value
from turtlemap.analysis.types import PinType
from turtlemap.languages.language import Profile


class Constructions:
    def __init__(
        self,
        profile: Profile,
        graph: Graph,
        evaluate: Callable[[m.Expr], Value],
        text: Callable[[m.Node], str],
    ) -> None:
        self._profile = profile
        self._graph = graph
        self._evaluate = evaluate
        self._text = text

    def format_text(self, expression: m.Template) -> Value:
        pieces: dict[str, Value] = {}
        for part in expression.parts:
            if isinstance(part, m.Interpolation):
                text = shorten(self._text(part.value), 30)
                if text not in pieces:
                    pieces[text] = self._evaluate(part.value)
        node = self._graph.add(
            "make", "Format text", expression.line, code=self._text(expression)
        )
        node.form = Form("value")
        for name, value in pieces.items():
            self._graph.connect(node, name, value)
        return self._graph.output(node, "", STR)

    def sequence(self, expression: m.Sequence) -> Value:
        kind_name, cat = self._profile.sequence_kinds.get(
            expression.kind, (expression.kind, "list")
        )
        inputs = [
            self._element(element, index)
            for index, element in enumerate(expression.elements)
        ]
        return self._make(kind_name, expression.line, inputs, PinType(kind_name, cat))

    def mapping(self, expression: m.Mapping) -> Value:
        inputs: list[tuple[str, Value]] = []
        for index, (key, value) in enumerate(zip(expression.keys, expression.values)):
            inputs += self._entry(index, key, value)
        label, cat = self._profile.mapping_kind
        return self._make(label, expression.line, inputs, PinType(label, cat))

    def _element(self, element: m.Expr, index: int) -> tuple[str, Value]:
        if isinstance(element, m.Spread):
            name = f"{self._profile.spread_prefix}{pin_name(element.value, 'items')}"
            return name, self._evaluate(element.value)
        return _element_name(element, index), self._evaluate(element)

    def _entry(
        self, index: int, key: m.Expr | None, value: m.Expr
    ) -> list[tuple[str, Value]]:
        if key is None:
            spread = self._profile.mapping_spread_prefix
            return [(f"{spread}{pin_name(value, 'mapping')}", self._evaluate(value))]
        if isinstance(key, m.Literal) and isinstance(key.value, str):
            return [(key.value or '""', self._evaluate(value))]
        return [
            (f"key {index + 1}", self._evaluate(key)),
            (f"value {index + 1}", self._evaluate(value)),
        ]

    def _make(
        self,
        label: str,
        line: int,
        inputs: Sequence[tuple[str, Value]],
        result: PinType,
    ) -> Value:
        node = self._graph.add("make", f"Make {label}", line)
        node.form = Form("build", label)
        for name, value in inputs:
            self._graph.connect(node, name, value)
        return self._graph.output(node, label, result)


def _element_name(element: m.Expr, index: int) -> str:
    return pin_name(element) if isinstance(element, (m.Name, m.Member)) else str(index)
