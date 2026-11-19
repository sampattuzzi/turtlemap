from collections.abc import Callable
from dataclasses import replace

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.callees import FUNCTION_PIN
from turtlemap.analysis.blueprint.canvas import GraphNode
from turtlemap.analysis.blueprint.statements.bindings import Bindings
from turtlemap.analysis.blueprint.statements.context import BuildContext
from turtlemap.analysis.blueprint.values import CALLABLE, Signature, Value
from turtlemap.analysis.types import PinType, native


class Closures:
    def __init__(
        self,
        context: BuildContext,
        bindings: Bindings,
        run: Callable[[BuildContext], None],
    ) -> None:
        self.context = context
        self.bindings = bindings
        self._run = run

    def define(self, statement: m.FunctionDef) -> None:
        self._build(statement.function, bound_to=statement.function.name)

    def function_value(self, function: m.Function) -> Value:
        return self._build(_declaration(function, self.context.profile.function_title))

    def update(self, expression: m.AugAssignExpr, out_name: str) -> Value:
        return self.bindings.update(expression, out_name)

    def assign_name(self, name: str, value: Value, line: int) -> None:
        self.bindings.assign_name(name, value, line)

    def _build(self, function: m.FunctionDecl, *, bound_to: str | None = None) -> Value:
        graph = self.context.graph
        title = (
            self.context.profile.function_title if function.anonymous else function.name
        )
        frame = graph.add("closure", title, function.line)
        value = graph.output(frame, FUNCTION_PIN, CALLABLE)
        if bound_to is not None:
            self.context.scope.bind(bound_to, value)
        child = self.context.nested(function, frame)
        self._run(child)
        signature = self._signature(function, frame, child)
        graph.signatures[frame.id] = signature
        typed = PinType(self._label(signature), "callable")
        frame.outs[0].type = typed
        value = replace(value, type=typed)
        if bound_to is not None:
            self.context.scope.bind(bound_to, value)
        return value

    def _signature(
        self, function: m.FunctionDecl, frame: GraphNode, child: BuildContext
    ) -> Signature:
        parameters = tuple(
            parameter.name
            for parameter in function.params
            if parameter.kind in ("positional_only", "positional")
        )
        return Signature(
            parameters,
            child.return_type or self._returned(frame),
            function.is_async,
            function.anonymous,
        )

    def _returned(self, frame: GraphNode) -> PinType:
        for node in self.context.graph.nodes:
            if node.parent == frame.id and node.kind == "return" and node.ins:
                return node.ins[0].type
        return PinType(self.context.profile.no_result_label, "none")

    def _label(self, signature: Signature) -> str:
        profile = self.context.profile
        result = (
            profile.awaitable_label
            if signature.is_async
            else native(signature.result, profile.literal_labels).label
        )
        prefix = "async " if signature.is_async else ""
        return f"{prefix}({', '.join(signature.parameters)}) ⇒ {result}"


def _declaration(function: m.Function, title: str) -> m.FunctionDecl:
    body = list(function.body)
    if function.expression is not None:
        body.append(
            m.Return(
                function.expression.line,
                function.expression.end_line,
                function.expression,
                origin=function.expression.origin,
            )
        )
    return m.FunctionDecl(
        function.line,
        function.end_line,
        function.name or title,
        function.params,
        None,
        body,
        is_async=function.is_async,
        anonymous=function.name is None,
        origin=function.origin,
    )
