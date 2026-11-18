from dataclasses import dataclass, field, replace

from code_blueprints.analysis import model as m
from code_blueprints.analysis.blueprint.lookups import TypeLookups
from code_blueprints.analysis.blueprint.values import Signature, Value
from code_blueprints.analysis.types import UNKNOWN, PinType
from code_blueprints.analysis.workspace.parsed import (
    ExternalRef,
    ParsedFunction,
    ParsedModule,
    SymbolRef,
)
from code_blueprints.languages.language import Profile

CHOSEN_CLASS = "class"
FUNCTION_PIN = "function"


@dataclass
class Callee:
    kind: str
    title: str
    pure: bool
    result: PinType = UNKNOWN
    target: SymbolRef | None = None
    external: str | None = None
    receiver: Value | None = None
    receiver_name: str = ""
    parameters: tuple[str, ...] = ()
    vararg: str | None = None
    parameter_types: dict[str, PinType] = field(default_factory=dict)
    note: str | None = None
    is_async: bool = False


class Callees:
    def __init__(self, lookups: TypeLookups) -> None:
        self._lookups = lookups
        self._workspace = lookups.workspace
        self._module = lookups.module
        self._profile = lookups.profile

    def local(self, name: str, value: Value) -> Callee:
        if (
            value.type.cat == "class"
            and value.type.ref is not None
            and self._workspace.parsed_class(value.type.ref) is not None
        ):
            constructor = self.constructor(value.type.ref)
            if value.node is None or name in self._profile.receiver_names:
                return constructor
            return replace(
                constructor,
                title=f"Make {name}",
                receiver=value,
                receiver_name=CHOSEN_CLASS,
            )
        return Callee("ext", name, pure=False, receiver=value, receiver_name=name)

    def closure(self, name: str, value: Value, signature: Signature) -> Callee:
        return Callee(
            "call",
            "Call" if signature.anonymous else name,
            pure=False,
            result=signature.result,
            receiver=value,
            receiver_name=FUNCTION_PIN,
            parameters=signature.parameters,
            is_async=signature.is_async,
        )

    def global_callee(self, dotted: str, line: int) -> Callee:
        head, _, rest = dotted.partition(".")
        pure = self.is_pure_global(dotted)
        if head in self._lookups.module_variables and rest:
            receiver_text, _, method = dotted.rpartition(".")
            receiver_type = (
                self._lookups.module_variable(head)
                if receiver_text == head
                else UNKNOWN
            )
            return self.method_named(
                self.receiver_title(dotted),
                method,
                Value(receiver_type, literal=receiver_text),
                pure=pure,
            )
        resolved = self._workspace.resolve(self._module, dotted)
        if isinstance(resolved, SymbolRef):
            if self._workspace.parsed_class(resolved) is not None and _same_last(
                dotted, resolved.sym
            ):
                return self.constructor(resolved)
            function = self._workspace.parsed_function(resolved)
            if function is not None:
                return self.function(
                    "call", dotted, resolved, function, pure=pure, bound=False
                )
        if isinstance(resolved, ExternalRef):
            return Callee("ext", dotted, pure=pure, external=external_name(resolved))
        if resolved is None and dotted in self._profile.builtin_names:
            return Callee(
                "ext",
                dotted,
                pure=pure,
                parameters=self._profile.builtin_parameters.get(dotted, ()),
                result=self._lookups.profile_type(
                    self._profile.builtin_results.get(dotted)
                ),
            )
        return Callee("ext", dotted, pure=pure)

    def constructor(self, ref: SymbolRef) -> Callee:
        name = ref.sym.rsplit(".", 1)[-1]
        result = self._lookups.system.class_type(ref)
        owner_module = self._workspace.module(ref.path)
        constructor = (
            owner_module.language.profile.constructor_name
            if owner_module is not None
            else self._profile.constructor_name
        )
        initializer = self._workspace.find_method(ref, constructor)
        if initializer is not None:
            function = self._workspace.parsed_function(initializer)
            module = self._workspace.module(initializer.path)
            if function is not None and module is not None:
                positional, vararg, parameter_types = self._signature(
                    function.node, module, skip_first=True
                )
                return Callee(
                    "make",
                    f"Make {name}",
                    pure=True,
                    result=result,
                    target=ref,
                    parameters=positional,
                    vararg=vararg,
                    parameter_types=parameter_types,
                )
        fields = self._lookups.class_fields(ref)
        return Callee(
            "make",
            f"Make {name}",
            pure=True,
            result=result,
            target=ref,
            parameters=tuple(fields),
            parameter_types=fields,
        )

    def function(
        self,
        kind: str,
        title: str,
        ref: SymbolRef,
        function: ParsedFunction,
        *,
        pure: bool,
        bound: bool,
        receiver: Value | None = None,
    ) -> Callee:
        module = self._workspace.module(ref.path)
        if module is None:
            return Callee(kind, title, pure=pure, target=ref, receiver=receiver)
        is_method = (
            function.class_qualname is not None and function.node.binding != "static"
        )
        skip_first = is_method and (bound or function.node.binding == "class")
        positional, vararg, parameter_types = self._signature(
            function.node, module, skip_first=skip_first
        )
        result = (
            self._lookups.resolver(module).annotation(function.node.returns)
            if function.node.returns is not None
            else UNKNOWN
        )
        return Callee(
            kind,
            title,
            pure=pure,
            result=result,
            target=ref,
            receiver=receiver,
            parameters=positional,
            vararg=vararg,
            parameter_types=parameter_types,
            is_async=function.node.is_async,
        )

    def method(self, function: m.Member, receiver: Value) -> Callee:
        return self.method_named(
            self.receiver_title(self._module.language.text(function), function.value),
            function.attr,
            receiver,
            pure=function.attr in self._profile.pure_methods,
        )

    def method_named(
        self, title: str, method: str, receiver: Value, *, pure: bool
    ) -> Callee:
        ref = receiver.type.ref
        found = (
            self._workspace.find_method(ref, method)
            if ref is not None and self._workspace.parsed_class(ref) is not None
            else None
        )
        function = self._workspace.parsed_function(found) if found is not None else None
        if found is not None and function is not None:
            return self.function(
                "method",
                title,
                found,
                function,
                pure=pure,
                bound=True,
                receiver=receiver,
            )
        result = (
            receiver.type
            if method in self._profile.same_type_methods and receiver.type.cat != "any"
            else self._lookups.profile_type(self._profile.method_results.get(method))
        )
        return Callee("method", title, pure=pure, result=result, receiver=receiver)

    def is_pure_global(self, dotted: str) -> bool:
        head, _, rest = dotted.partition(".")
        if head in self._lookups.module_variables and rest:
            return dotted.rsplit(".", 1)[-1] in self._profile.pure_methods
        resolved = self._workspace.resolve(self._module, dotted)
        if isinstance(resolved, SymbolRef):
            return self._workspace.parsed_class(resolved) is not None and _same_last(
                dotted, resolved.sym
            )
        if isinstance(resolved, ExternalRef):
            return _external_is_pure(self._profile, external_name(resolved))
        if (
            resolved is None
            and dotted in self._profile.builtin_names
            and dotted not in self._module.imports
        ):
            return dotted in self._profile.pure_builtins or dotted[:1].isupper()
        return False

    def folds_global(self, dotted: str) -> bool:
        if dotted.rsplit(".", 1)[-1][:1].isupper():
            return False
        if isinstance(self._workspace.resolve(self._module, dotted), SymbolRef):
            return False
        return self.is_pure_global(dotted)

    def folded_call_type(self, call: m.Call, types: dict[int, PinType]) -> PinType:
        dotted = m.dotted_name(call.func) or ""
        if dotted in self._profile.builtin_results:
            return self._lookups.profile_type(self._profile.builtin_results[dotted])
        resolved = self._workspace.resolve(self._module, dotted) if dotted else None
        if (
            isinstance(resolved, ExternalRef)
            and external_name(resolved).split(".")[0] in self._profile.numeric_modules
            and call.args
        ):
            first = types.get(id(call.args[0]), UNKNOWN)
            return first if first.cat in ("int", "float") else UNKNOWN
        return UNKNOWN

    def receiver_title(self, text: str, receiver: m.Expr | None = None) -> str:
        if receiver is not None and self.is_super_call(receiver):
            call = "()" if isinstance(receiver, m.Call) else ""
            return f"{self._profile.super_name}{call}.{text.rsplit('.', 1)[-1]}"
        if receiver is not None and m.dotted_name(receiver) is None:
            return text.rsplit(".", 1)[-1]
        parts = text.split(".")
        return ".".join(parts[-2:])

    def is_super_call(self, expression: m.Expr) -> bool:
        if isinstance(expression, m.Call):
            expression = expression.func
        return (
            isinstance(expression, m.Name) and expression.id == self._profile.super_name
        )

    def _signature(
        self,
        definition: m.FunctionDecl,
        module: ParsedModule,
        *,
        skip_first: bool,
    ) -> tuple[tuple[str, ...], str | None, dict[str, PinType]]:
        positional = [
            parameter
            for parameter in definition.params
            if parameter.kind in ("positional_only", "positional")
        ]
        if skip_first and definition.implicit_receiver is None:
            positional = positional[1:]
        resolver = self._lookups.resolver(module)
        parameter_types = {
            parameter.name: resolver.annotation(parameter.annotation)
            for parameter in definition.params
            if parameter.annotation is not None
        }
        vararg = next((p.name for p in definition.params if p.kind == "variadic"), None)
        return (
            tuple(parameter.name for parameter in positional),
            vararg,
            parameter_types,
        )


def external_name(resolved: ExternalRef) -> str:
    return f"{resolved.module}.{resolved.name}" if resolved.name else resolved.module


def _external_is_pure(profile: Profile, external: str) -> bool:
    return (
        external in profile.pure_externals
        or external.split(".")[0] in profile.pure_external_modules
        or external.rsplit(".", 1)[-1][:1].isupper()
    )


def _same_last(dotted: str, sym: str) -> bool:
    return dotted.rsplit(".", 1)[-1] == sym.rsplit(".", 1)[-1]
