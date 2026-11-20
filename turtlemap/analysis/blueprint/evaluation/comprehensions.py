from collections.abc import Callable, Iterable
from contextlib import ExitStack
from dataclasses import replace

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.canvas import Graph, GraphNode
from turtlemap.analysis.blueprint.code_shapes import flat_targets, target_label
from turtlemap.analysis.blueprint.lookups import TypeLookups
from turtlemap.analysis.blueprint.scope import Scope
from turtlemap.analysis.blueprint.text import LABEL_LIMIT, shorten
from turtlemap.analysis.blueprint.values import BOOL, Value
from turtlemap.analysis.types import UNKNOWN, PinType
from turtlemap.languages.language import ComprehensionShape

KEEP_IF = "keep if"
RESULTS_TITLE = "Results"
FILTER_TITLE = "Filter"


class Comprehensions:
    def __init__(
        self,
        lookups: TypeLookups,
        scope: Scope,
        graph: Graph,
        evaluate: Callable[[m.Expr], Value],
        text: Callable[[m.Node], str],
    ) -> None:
        self._lookups = lookups
        self._profile = lookups.profile
        self._scope = scope
        self._graph = graph
        self._evaluate = evaluate
        self._text = text

    def value(self, expression: m.Comprehension) -> Value:
        shape = self._profile.comprehensions[expression.kind]
        outer, first_items = self._frame_for(expression.clauses[0])
        outer.badge = shape.badge
        result = self._graph.output(outer, "", PinType(shape.label, shape.cat))
        results: list[Value] = []
        with self._scope.local_bindings(expression.bound), ExitStack() as inside:
            for index, clause in enumerate(expression.clauses):
                frame, items = (
                    (outer, first_items) if index == 0 else self._frame_for(clause)
                )
                self._bind_targets(frame, items, clause)
                inside.enter_context(self._graph.inside(frame.id))
                conditions = [self._evaluate(test) for test in clause.conditions]
                if index == len(expression.clauses) - 1:
                    results = [self._evaluate(part) for part in expression.results]
                    self._band(
                        RESULTS_TITLE,
                        clause.line,
                        zip(shape.results, results),
                        conditions,
                    )
                elif conditions:
                    self._band(FILTER_TITLE, clause.line, [], conditions)
        typed = self._result_type(shape, results)
        outer.outs[0].type = typed
        return replace(result, type=typed)

    def _frame_for(self, clause: m.ComprehensionClause) -> tuple[GraphNode, Value]:
        items = self._evaluate(clause.iterable)
        names = ", ".join(self._label(target) for target in flat_targets(clause.target))
        source = shorten(self._text(clause.iterable), LABEL_LIMIT)
        frame = self._graph.add(
            "comprehension",
            f"{names} in {source}",
            clause.line,
            note="async for" if clause.is_async else None,
        )
        self._graph.connect(frame, "items", items)
        return frame, items

    def _bind_targets(
        self, frame: GraphNode, items: Value, clause: m.ComprehensionClause
    ) -> None:
        targets = flat_targets(clause.target)
        element = self._lookups.element(items) if len(targets) == 1 else UNKNOWN
        for target in targets:
            output = self._graph.output(frame, self._label(target), element)
            name = _bound_name(target)
            if name is not None:
                self._scope.bind(name, output)

    def _band(
        self,
        title: str,
        line: int,
        results: Iterable[tuple[str, Value]],
        conditions: list[Value],
    ) -> None:
        band = self._graph.add("collect", title, line)
        for name, value in results:
            self._graph.connect(band, name, value)
        for condition in conditions:
            self._graph.connect(band, KEEP_IF, condition, BOOL)

    def _result_type(self, shape: ComprehensionShape, results: list[Value]) -> PinType:
        known = [value.type for value in results]
        if not known or any(pin.cat == "any" for pin in known):
            return PinType(shape.label, shape.cat)
        labels = ", ".join(pin.label for pin in known)
        items = known[0].ref if len(known) == 1 else None
        return PinType(f"{shape.label}[{labels}]", shape.cat, items=items)

    def _label(self, target: m.Expr) -> str:
        return target_label(target, self._profile.spread_prefix, self._text)


def _bound_name(target: m.Expr) -> str | None:
    if isinstance(target, m.Name):
        return target.id
    if isinstance(target, m.Spread):
        return _bound_name(target.value)
    return None
