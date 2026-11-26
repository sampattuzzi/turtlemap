from collections.abc import Callable
from typing import Protocol, TypeVar

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.evaluation.attributes import AttributeReads
from turtlemap.analysis.blueprint.callees import Callees
from turtlemap.analysis.blueprint.evaluation.calls import Calls
from turtlemap.analysis.blueprint.canvas import Flow
from turtlemap.analysis.blueprint.evaluation.comprehensions import Comprehensions
from turtlemap.analysis.blueprint.evaluation.constructions import Constructions
from turtlemap.analysis.blueprint.evaluation.folding import Folding
from turtlemap.analysis.blueprint.lookups import TypeLookups
from turtlemap.analysis.blueprint.evaluation.operations import Operations
from turtlemap.analysis.blueprint.scope import Scope
from turtlemap.analysis.blueprint.values import CALLABLE, Value
from turtlemap.analysis.types import UNKNOWN, PinType
from turtlemap.analysis.workspace.parsed import SymbolRef

_Handler = Callable[[m.Expr], Value]
_Expression = TypeVar("_Expression", bound=m.Expr)


class Nested(Protocol):
    def function_value(self, function: m.Function) -> Value: ...

    def update(self, expression: m.AugAssignExpr, out_name: str) -> Value: ...

    def assign_name(self, name: str, value: Value, line: int) -> None: ...


class Expressions:
    def __init__(
        self,
        lookups: TypeLookups,
        callees: Callees,
        scope: Scope,
        flow: Flow,
        owner: SymbolRef | None,
        function: m.FunctionDecl,
    ) -> None:
        self._lookups = lookups
        self._scope = scope
        self._flow = flow
        self._graph = flow.graph
        self._language = lookups.module.language
        self._profile = lookups.profile
        self.folding = Folding(lookups, callees, scope, flow.graph, self.value)
        self.calls = Calls(lookups, callees, scope, flow, owner, self.value)
        self.attributes = AttributeReads(
            lookups, scope, flow.graph, function, self.value
        )
        self.operations = Operations(lookups, flow.graph, self.value, self._text)
        self.constructions = Constructions(
            self._profile, flow.graph, self.value, self._text
        )
        self.comprehensions = Comprehensions(
            lookups, scope, flow, self.value, self._text
        )
        self._handlers = self._expression_handlers()
        self.nested: Nested | None = None

    def value(
        self, expression: m.Expr, *, exec_candidate: bool = False, out_name: str = ""
    ) -> Value:
        literal = self._lookups.literal(expression)
        if literal is not None:
            return literal
        if isinstance(expression, m.Name):
            return self._scope.value_of(expression.id, expression.line)
        if self.folding.folds(expression, named=bool(out_name)):
            return self.folding.expression(expression, out_name)
        if isinstance(expression, m.Call):
            return self.calls.value(
                expression, exec_candidate=exec_candidate, out_name=out_name
            )
        if isinstance(expression, m.Await):
            return self.calls.awaited(
                expression, exec_candidate=exec_candidate, out_name=out_name
            )
        if isinstance(expression, m.AugAssignExpr) and self.nested is not None:
            return self.nested.update(expression, out_name)
        handler = self._handlers.get(type(expression))
        if handler is None:
            return self._opaque(expression, self._text(expression), UNKNOWN, code=None)
        return handler(expression)

    def yield_value(self, expression: m.Yield, *, discard: bool) -> Value:
        value = self.value(expression.value) if expression.value is not None else None
        node = self._graph.add(
            "return",
            "Yield from" if expression.delegate else "Yield",
            expression.line,
        )
        if value is not None:
            self._graph.connect(node, "value", value)
        self._flow.step(node)
        if discard:
            return self._lookups.none_literal()
        return self._graph.output(node, "sent", UNKNOWN)

    def _expression_handlers(self) -> dict[type[m.Expr], _Handler]:
        return dict(
            [
                _on(m.Member, self.attributes.read),
                _on(m.Logical, self.operations.logical),
                _on(m.Binary, self.operations.binary),
                _on(m.Unary, self.operations.unary),
                _on(m.Compare, self.operations.compare),
                _on(m.Conditional, self._conditional),
                _on(m.Subscript, self.operations.subscript),
                _on(m.Template, self.constructions.format_text),
                _on(m.Sequence, self.constructions.sequence),
                _on(m.Mapping, self.constructions.mapping),
                _on(m.Comprehension, self.comprehensions.value),
                _on(m.Function, self._function_value),
                _on(m.AssignExpr, self._assign_expression),
                _on(m.Spread, self._inner),
                _on(m.Yield, self._yield),
                _on(m.Interpolation, self._inner),
            ]
        )

    def _conditional(self, expression: m.Conditional) -> Value:
        condition = self.value(expression.test)
        return self._scope.select(
            condition,
            self.value(expression.body),
            self.value(expression.orelse),
            expression.line,
        )

    def _function_value(self, expression: m.Function) -> Value:
        if self.nested is not None:
            return self.nested.function_value(expression)
        return self._opaque(
            expression,
            expression.name or self._profile.function_title,
            CALLABLE,
            code=self._text(expression),
        )

    def _assign_expression(self, expression: m.AssignExpr) -> Value:
        value = self.value(expression.value, out_name=expression.target.id)
        if self.nested is not None:
            self.nested.assign_name(expression.target.id, value, expression.line)
        else:
            self._scope.bind(expression.target.id, value)
        return value

    def _inner(self, expression: m.Spread | m.Interpolation) -> Value:
        return self.value(expression.value)

    def _yield(self, expression: m.Yield) -> Value:
        return self.yield_value(expression, discard=False)

    def _opaque(
        self, expression: m.Expr, title: str, result: PinType, *, code: str | None
    ) -> Value:
        inputs = [
            (name, self._scope.value_of(name, expression.line))
            for name in _free_names(expression)
            if name in self._scope.env or name in self._lookups.module_variables
        ]
        node = self._graph.add("ext", title, expression.line, code=code)
        for name, value in inputs:
            self._graph.connect(node, name, value)
        return self._graph.output(node, "", result)

    def _text(self, node: m.Node) -> str:
        return self._language.text(node)


def _on(
    kind: type[_Expression], handle: Callable[[_Expression], Value]
) -> tuple[type[m.Expr], _Handler]:
    def run(expression: m.Expr) -> Value:
        assert isinstance(expression, kind)
        return handle(expression)

    return kind, run


def _free_names(expression: m.Expr) -> list[str]:
    bound: set[str] = set()
    for node in m.walk(expression):
        if isinstance(node, m.Comprehension):
            bound.update(node.bound)
        elif isinstance(node, m.Function):
            bound.update(parameter.name for parameter in node.params)
        elif isinstance(node, m.AssignExpr):
            bound.add(node.target.id)
    names: list[str] = []
    for node in m.walk(expression):
        if (
            isinstance(node, m.Name)
            and not node.store
            and node.id not in bound
            and node.id not in names
        ):
            names.append(node.id)
    return names
