from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.callees import Callee, Callees
from turtlemap.analysis.blueprint.canvas import Flow, GraphNode
from turtlemap.analysis.blueprint.lookups import TypeLookups
from turtlemap.analysis.blueprint.scope import Scope
from turtlemap.analysis.blueprint.text import pin_name, short_name
from turtlemap.analysis.blueprint.values import Signature, Value
from turtlemap.analysis.types import UNKNOWN, PinType
from turtlemap.analysis.workspace.parsed import SymbolRef


@dataclass(frozen=True)
class Argument:
    name: str
    value: Value
    pin_type: PinType


class Calls:
    def __init__(
        self,
        lookups: TypeLookups,
        callees: Callees,
        scope: Scope,
        flow: Flow,
        owner: SymbolRef | None,
        evaluate: Callable[[m.Expr], Value],
    ) -> None:
        self._lookups = lookups
        self._callees = callees
        self._scope = scope
        self._flow = flow
        self._graph = flow.graph
        self._owner = owner
        self._evaluate = evaluate
        self._profile = lookups.profile
        self._language = lookups.module.language

    def value(self, call: m.Call, *, exec_candidate: bool, out_name: str) -> Value:
        if self._callees.is_super_call(call) and not self._scope.is_local(
            self._profile.super_name
        ):
            return self._super_value()
        return self.call(call, exec_candidate=exec_candidate, out_names=(out_name,))[0]

    def awaited(
        self, expression: m.Await, *, exec_candidate: bool, out_name: str
    ) -> Value:
        if isinstance(expression.value, m.Call):
            return self.call(
                expression.value,
                exec_candidate=exec_candidate,
                out_names=(out_name,),
                awaited=True,
            )[0]
        value = self._evaluate(expression.value)
        node = self._graph.add("ext", "await", expression.line, note="awaits")
        self._graph.connect(node, "awaitable", value)
        if exec_candidate:
            self._flow.step(node)
        return self._graph.output(node, out_name, UNKNOWN)

    def call(
        self,
        call: m.Call,
        *,
        exec_candidate: bool,
        out_names: Sequence[str],
        awaited: bool = False,
    ) -> list[Value]:
        callee = self.resolve_callee(call)
        arguments = self.arguments(call, callee)
        node = self._graph.add(
            callee.kind,
            callee.title,
            call.line,
            target=callee.target,
            external=callee.external,
            note=callee.note,
        )
        if awaited:
            node.notes.append("awaits")
        elif callee.is_async:
            node.notes.append("not awaited")
            callee = replace(
                callee, result=PinType(self._profile.awaitable_label, "any")
            )
        if callee.receiver is not None:
            self._graph.connect(
                node,
                callee.receiver_name or self._profile.instance_receiver,
                callee.receiver,
            )
        self.connect_arguments(node, arguments)
        if exec_candidate and not callee.pure:
            self._flow.step(node)
        return self._outputs(node, callee, out_names)

    def arguments(
        self, call: m.Call, callee: Callee, first_fallback: str | None = None
    ) -> list[Argument]:
        arguments = [
            self._argument(
                self._positional_name(argument, index, callee, first_fallback),
                argument,
                callee,
            )
            for index, argument in enumerate(call.args)
        ]
        for keyword in call.keywords:
            name = (
                keyword.arg
                if keyword.arg is not None
                else f"{self._profile.mapping_spread_prefix}"
                f"{pin_name(keyword.value, 'kwargs')}"
            )
            arguments.append(self._argument(name, keyword.value, callee))
        return arguments

    def connect_arguments(self, node: GraphNode, arguments: Sequence[Argument]) -> None:
        for argument in arguments:
            self._graph.connect(node, argument.name, argument.value, argument.pin_type)

    def resolve_callee(self, call: m.Call) -> Callee:
        function = call.func
        if isinstance(function, m.Name):
            if function.id in self._scope.local_functions:
                return Callee("ext", function.id, pure=False, note="Local function")
            if self._scope.is_local(function.id):
                value = self._scope.value_of(function.id, call.line)
                signature = self._signature_of(value)
                if signature is not None:
                    return self._callees.closure(function.id, value, signature)
                return self._callees.local(function.id, value)
            return self._callees.global_callee(function.id, call.line)
        if isinstance(function, m.Member):
            dotted = m.dotted_name(function)
            if dotted is not None and not self._scope.is_local(dotted.split(".")[0]):
                return self._callees.global_callee(dotted, call.line)
            return self._callees.method(function, self._receiver(function))
        receiver = self._evaluate(function)
        signature = self._signature_of(receiver)
        if signature is not None:
            return self._callees.closure(
                self._language.text(function), receiver, signature
            )
        return Callee(
            "ext",
            self._language.text(function),
            pure=False,
            receiver=receiver,
            receiver_name="callable",
        )

    def _receiver(self, function: m.Member) -> Value:
        base = function.value
        if (
            isinstance(base, m.Name)
            and function.attr not in self._profile.pure_methods
            and self._scope.is_variable(base.id)
        ):
            reference = self._scope.known_reference(base.id, function.line)
            if reference is not None:
                return reference
        return self._evaluate(base)

    def _signature_of(self, value: Value) -> Signature | None:
        return self._graph.signatures.get(value.node) if value.node else None

    def call_is_pure(self, call: m.Call) -> bool:
        function = call.func
        if isinstance(function, m.Name):
            if function.id in self._scope.local_functions:
                return False
            if self._scope.is_local(function.id):
                return self._is_class_value(function.id)
            return self._callees.is_pure_global(function.id)
        if isinstance(function, m.Member):
            dotted = m.dotted_name(function)
            if dotted is not None and not self._scope.is_local(dotted.split(".")[0]):
                return self._callees.is_pure_global(dotted)
            return function.attr in self._profile.pure_methods
        return False

    def _is_class_value(self, name: str) -> bool:
        binding = self._scope.env.get(name)
        return (
            isinstance(binding, Value)
            and binding.type.cat == "class"
            and binding.type.ref is not None
        )

    def _outputs(
        self, node: GraphNode, callee: Callee, out_names: Sequence[str]
    ) -> list[Value]:
        if not out_names:
            return []
        if callee.kind == "make" and len(out_names) == 1:
            name = short_name(callee.title.removeprefix("Make "))
            return [self._graph.output(node, name, callee.result)]
        if len(out_names) == 1:
            return [self._graph.output(node, out_names[0], callee.result)]
        return [self._graph.output(node, name, UNKNOWN) for name in out_names]

    def _positional_name(
        self,
        argument: m.Expr,
        index: int,
        callee: Callee,
        first_fallback: str | None,
    ) -> str:
        if isinstance(argument, m.Spread):
            return f"{self._profile.spread_prefix}{pin_name(argument.value, 'args')}"
        if index < len(callee.parameters):
            return callee.parameters[index]
        if callee.vararg is not None:
            return f"{self._profile.spread_prefix}{callee.vararg}"
        if index == 0 and first_fallback is not None:
            return first_fallback
        return _argument_name(argument, index)

    def _argument(self, name: str, expression: m.Expr, callee: Callee) -> Argument:
        value = self._evaluate(expression)
        declared = callee.parameter_types.get(name)
        return Argument(
            name,
            value,
            declared if declared is not None and declared.cat != "any" else value.type,
        )

    def _super_value(self) -> Value:
        owner = self._owner
        if owner is not None:
            for _, base in self._lookups.workspace.base_classes(owner):
                if (
                    isinstance(base, SymbolRef)
                    and self._lookups.workspace.parsed_class(base) is not None
                ):
                    return Value(
                        self._lookups.system.class_type(base), literal="super()"
                    )
        return Value(UNKNOWN, literal="super()")


def _argument_name(argument: m.Expr, index: int) -> str:
    if isinstance(argument, (m.Name, m.Member)):
        return pin_name(argument)
    return f"arg{index + 1}"
