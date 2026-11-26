from collections.abc import Callable
from dataclasses import dataclass, replace

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.canvas import Flow, GraphNode
from turtlemap.analysis.blueprint.code_shapes import flat_targets, target_label
from turtlemap.analysis.blueprint.lookups import TypeLookups
from turtlemap.analysis.blueprint.scope import Scope
from turtlemap.analysis.blueprint.text import LABEL_LIMIT, shorten
from turtlemap.analysis.blueprint.values import BOOL, Value
from turtlemap.analysis.types import UNKNOWN, PinType
from turtlemap.languages.language import ComprehensionShape

KEEP_IF = "keep if"
YIELD_FROM = "yield from"
RESULTS_TITLE = "Results"


@dataclass(frozen=True)
class _Clause:
    frame: GraphNode
    result: Value
    elements: list[PinType]


class Comprehensions:
    def __init__(
        self,
        lookups: TypeLookups,
        scope: Scope,
        flow: Flow,
        evaluate: Callable[[m.Expr], Value],
        text: Callable[[m.Node], str],
    ) -> None:
        self._lookups = lookups
        self._profile = lookups.profile
        self._scope = scope
        self._flow = flow
        self._graph = flow.graph
        self._evaluate = evaluate
        self._text = text
        self._depth = 0

    def value(self, expression: m.Comprehension) -> Value:
        shape = self._profile.comprehensions[expression.kind]
        self._depth += 1
        try:
            with self._scope.local_bindings(expression.bound):
                outer = self._clause(expression, 0, shape)
        finally:
            self._depth -= 1
        outer.frame.badge = shape.badge
        if self._depth == 0 and self._reads_changing_values(outer.frame):
            self._flow.step(outer.frame)
        return outer.result

    def _reads_changing_values(self, frame: GraphNode) -> bool:
        return any(
            pin.cell
            for node in self._graph.nodes
            if self._graph.encloses(frame.id, node.id)
            for pin in node.ins
        )

    def _clause(
        self, expression: m.Comprehension, index: int, shape: ComprehensionShape
    ) -> _Clause:
        clause = expression.clauses[index]
        produces = shape if index == 0 else self._profile.comprehensions["generator"]
        items = self._evaluate(clause.iterable)
        frame = self._frame(clause, items)
        result = self._graph.output(frame, "", PinType(produces.label, produces.cat))
        self._bind_targets(frame, items, clause)
        with self._graph.inside(frame.id):
            conditions = [self._evaluate(test) for test in clause.conditions]
            if index == len(expression.clauses) - 1:
                values = [self._evaluate(part) for part in expression.results]
                pins = list(zip(shape.results, values))
                elements = [value.type for value in values]
            else:
                inner = self._clause(expression, index + 1, shape)
                pins = [(YIELD_FROM, inner.result)]
                elements = inner.elements
            self._band(clause.line, pins, conditions)
        typed = _result_type(produces, elements)
        frame.outs[0].type = typed
        return _Clause(frame, replace(result, type=typed), elements)

    def _frame(self, clause: m.ComprehensionClause, items: Value) -> GraphNode:
        names = ", ".join(self._label(target) for target in flat_targets(clause.target))
        source = shorten(self._text(clause.iterable), LABEL_LIMIT)
        frame = self._graph.add(
            "comprehension",
            f"{names} in {source}",
            clause.line,
            note="async for" if clause.is_async else None,
        )
        self._graph.connect(frame, "items", items)
        return frame

    def _bind_targets(
        self, frame: GraphNode, items: Value, clause: m.ComprehensionClause
    ) -> None:
        targets = flat_targets(clause.target)
        single = len(targets) == 1
        element = self._lookups.element(items) if single else UNKNOWN
        annotation = self._lookups.element_annotation(items) if single else None
        for target in targets:
            output = self._graph.output(frame, self._label(target), element, annotation)
            name = _bound_name(target)
            if name is not None:
                self._scope.bind(name, output)

    def _band(
        self, line: int, pins: list[tuple[str, Value]], conditions: list[Value]
    ) -> None:
        band = self._graph.add("collect", RESULTS_TITLE, line)
        for name, value in pins:
            self._graph.connect(band, name, value)
        for condition in conditions:
            self._graph.connect(band, KEEP_IF, condition, BOOL)

    def _label(self, target: m.Expr) -> str:
        return target_label(target, self._profile.spread_prefix, self._text)


def _result_type(shape: ComprehensionShape, elements: list[PinType]) -> PinType:
    if len(elements) != len(shape.results) or any(pin.cat == "any" for pin in elements):
        return PinType(shape.label, shape.cat)
    labels = ", ".join(pin.label for pin in elements)
    items = elements[0].ref if len(elements) == 1 else None
    return PinType(f"{shape.label}[{labels}]", shape.cat, items=items)


def _bound_name(target: m.Expr) -> str | None:
    if isinstance(target, m.Name):
        return target.id
    if isinstance(target, m.Spread):
        return _bound_name(target.value)
    return None
