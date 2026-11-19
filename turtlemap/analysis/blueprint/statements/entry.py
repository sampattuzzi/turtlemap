from dataclasses import replace
from turtlemap.analysis.types import (
    UNKNOWN,
    PinType,
)
from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.canvas import (
    GraphNode,
)
from turtlemap.analysis.blueprint.statements.context import BuildContext


class EntryNode:
    def __init__(self, context: BuildContext) -> None:
        self.context = context

    def node(self) -> GraphNode:
        function = self.context.function.node
        node = self.context.graph.add("entry", function.name, function.line)
        self._bind_receiver(node, function)
        self.bind_parameters(node)
        return node

    def bind_parameters(self, node: GraphNode) -> None:
        function = self.context.function.node
        positional = [
            parameter
            for parameter in function.params
            if parameter.kind in ("positional_only", "positional")
        ]
        for index, parameter in enumerate(positional):
            self._bind_parameter(
                node,
                parameter.name,
                parameter.name,
                self._parameter_type(parameter, index),
            )
        profile = self.context.profile
        self._bind_spread(
            node, function, "variadic", profile.spread_prefix, profile.variadic_label
        )
        for parameter in function.params:
            if parameter.kind == "keyword_only":
                self._bind_parameter(
                    node,
                    parameter.name,
                    parameter.name,
                    self._parameter_type(parameter, -1),
                )
        self._bind_spread(
            node,
            function,
            "variadic_keyword",
            profile.mapping_spread_prefix,
            profile.keywords_label,
        )

    def _bind_receiver(self, node: GraphNode, function: m.FunctionDecl) -> None:
        owner = self.context.owner_ref()
        if function.implicit_receiver is None or owner is None:
            return
        self.context.scope.bind(
            function.implicit_receiver,
            self.context.graph.output(
                node,
                function.implicit_receiver,
                self.context.types.class_type(owner),
            ),
        )

    def _bind_spread(
        self,
        node: GraphNode,
        function: m.FunctionDecl,
        kind: str,
        prefix: str,
        label: str,
    ) -> None:
        category = "list" if kind == "variadic" else "map"
        for parameter in function.params:
            if parameter.kind == kind:
                inner = self.context.lookups.annotation(parameter.annotation)
                self._bind_parameter(
                    node,
                    parameter.name,
                    f"{prefix}{parameter.name}",
                    PinType(label.format(inner.label), category),
                )

    def _bind_parameter(
        self, node: GraphNode, name: str, pin: str, pin_type: PinType
    ) -> None:
        annotation = self.context.parameter_annotations.get(name)
        self.context.scope.bind(
            name,
            self.context.graph.output(
                node,
                pin,
                pin_type,
                (annotation, self.context.module) if annotation is not None else None,
            ),
        )

    def _parameter_type(self, parameter: m.Parameter, index: int) -> PinType:
        owner = self.context.owner_ref()
        function = self.context.function.node
        if (
            index == 0
            and self.context.frame is None
            and owner is not None
            and parameter.annotation is None
            and function.implicit_receiver is None
        ):
            if function.binding == "static":
                return UNKNOWN
            owner_type = self.context.types.class_type(owner)
            if function.binding == "class":
                return replace(
                    owner_type, cat="class", label=f"type[{owner_type.label}]"
                )
            return owner_type
        return self.context.lookups.annotation(parameter.annotation)
