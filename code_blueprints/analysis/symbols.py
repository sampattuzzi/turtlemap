from typing import Any

from code_blueprints.analysis import model as m
from code_blueprints.analysis.import_summary import module_imports
from code_blueprints.analysis.unpacking import UnpackedField, receiver_fields
from code_blueprints.analysis.type_parameters import (
    FoundParameter,
    TypeParameters,
    bound_names,
)
from code_blueprints.analysis.types import (
    PinType,
    TypeResolver,
    TypeSystem,
    UNKNOWN,
    literal_type,
    native,
)
from code_blueprints.analysis.workspace.parsed import (
    ExternalRef,
    ParsedClass,
    ParsedFunction,
    ParsedModule,
    SymbolRef,
)

_MAX_VALUE = 48


def module_summary(types: TypeSystem, module: ParsedModule) -> dict[str, Any]:
    resolver = types.resolver(module)
    generics = TypeParameters(types.workspace)
    symbols: list[dict[str, Any]] = []
    for name, qualname in module.top_level.items():
        if qualname in module.classes:
            symbols.extend(
                _class_summaries(
                    types, resolver, module, module.classes[qualname], generics
                )
            )
        elif qualname in module.functions:
            symbols.append(
                function_summary(resolver, module, module.functions[qualname], generics)
            )
    symbols.sort(key=lambda s: int(s["line"]))
    summary: dict[str, Any] = {
        "path": module.path,
        "name": module.name,
        "doc": _first_paragraph(module.code.doc),
        "symbols": symbols,
        "constants": _constants(resolver, module),
        "typeVars": [
            [found.parameter.name, found.line, _bound_type(types, found)]
            for found in generics.declared(module).values()
        ],
        "imports": module_imports(types, module),
        "lines": len(module.lines),
    }
    if module.language.name != "python":
        summary["lang"] = module.language.name
    return summary


def function_summary(
    resolver: TypeResolver,
    module: ParsedModule,
    function: ParsedFunction,
    generics: TypeParameters | None = None,
    inherited: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    node = function.node
    profile = module.language.profile
    summary: dict[str, Any] = {
        "kind": "function",
        "name": node.name,
        "qual": function.qualname,
        "line": node.line,
        "end": node.end_line or node.line,
        "complexity": m.decision_points(node) + 1,
        "params": parameters(resolver, module, function),
        "returns": (
            resolver.annotation(node.returns).to_json()
            if node.returns is not None
            else (
                PinType(profile.none_text, "none").to_json()
                if node.is_constructor
                else UNKNOWN.to_json()
            )
        ),
    }
    if node.is_async:
        summary["async"] = True
    doc = _first_paragraph(node.doc)
    if doc:
        summary["doc"] = doc
    decorators = [module.language.text(d) for d in node.decorators]
    if decorators:
        summary["decorators"] = decorators
    if node.anonymous:
        summary["anonymous"] = True
    own = [
        found.parameter.name
        for found in (generics or TypeParameters(resolver.system.workspace)).mentioned(
            module, _annotations(node)
        )
        if found.parameter.name not in inherited
    ]
    if own:
        summary["typeParams"] = own
    return summary


def parameters(
    resolver: TypeResolver, module: ParsedModule, function: ParsedFunction
) -> list[list[Any]]:
    profile = module.language.profile
    out: list[list[Any]] = []
    index = 0
    for parameter in function.node.params:
        if parameter.kind in ("positional_only", "positional"):
            out.append(_param(resolver, module, function, parameter, index))
            index += 1
        elif parameter.kind == "keyword_only":
            out.append(_param(resolver, module, function, parameter, -1))
        elif parameter.kind == "variadic":
            out.append(
                [
                    f"{profile.spread_prefix}{parameter.name}",
                    PinType(
                        profile.variadic_label.format(_label(resolver, parameter)),
                        "list",
                    ).to_json(),
                ]
            )
        else:
            out.append(
                [
                    f"{profile.mapping_spread_prefix}{parameter.name}",
                    PinType(
                        profile.keywords_label.format(_label(resolver, parameter)),
                        "map",
                    ).to_json(),
                ]
            )
    return out


def class_fields(
    types: TypeSystem, ref: SymbolRef
) -> list[tuple[str, PinType, str | None]]:
    cached = types.field_cache.get(ref)
    if cached is not None:
        return cached
    module = types.workspace.module(ref.path)
    parsed = types.workspace.parsed_class(ref)
    if module is None or parsed is None:
        return []
    fields = _fields(
        types,
        types.resolver(module),
        module,
        parsed,
        types.class_category(ref) == "enum",
    )
    types.field_cache[ref] = fields
    return fields


def module_constants(module: ParsedModule) -> list[tuple[str, m.Assign]]:
    found: list[tuple[str, m.Assign]] = []
    for statement in module.body:
        if isinstance(statement, m.Assign) and module.language.is_constant(statement):
            target = statement.targets[0]
            assert isinstance(target, m.Name)
            found.append((target.id, statement))
    return found


def _class_summaries(
    types: TypeSystem,
    resolver: TypeResolver,
    module: ParsedModule,
    parsed: ParsedClass,
    generics: TypeParameters,
) -> list[dict[str, Any]]:
    parameters = generics.mentioned(module, parsed.node.bases)
    inherited = frozenset(found.parameter.name for found in parameters)
    ref = SymbolRef(module.path, parsed.qualname)
    category = types.class_category(ref)
    is_enum = category == "enum"
    bases, external_bases = _bases(types, ref)
    fields = class_fields(types, ref)
    summary: dict[str, Any] = {
        "kind": "enum" if is_enum else "class",
        "name": parsed.qualname,
        "qual": parsed.qualname,
        "cat": category,
        "line": parsed.node.line,
        "end": parsed.node.end_line or parsed.node.line,
        "bases": bases,
        "methods": [
            function_summary(resolver, module, module.functions[q], generics, inherited)
            for q in parsed.methods.values()
            if q in module.functions
        ],
    }
    stereo = types.stereotype(ref)
    if stereo:
        summary["stereo"] = stereo
    if external_bases:
        summary["extBases"] = external_bases
    if parameters:
        summary["typeParams"] = [
            [found.parameter.name, _bound_type(types, found)] for found in parameters
        ]
    summary.update(_field_lists(fields, is_enum))
    doc = _first_paragraph(parsed.node.doc)
    if doc:
        summary["doc"] = doc
    out = [summary]
    for child in _nested_classes(module, parsed):
        out.extend(_class_summaries(types, resolver, module, child, generics))
    return out


def _bases(types: TypeSystem, ref: SymbolRef) -> tuple[list[dict[str, str]], list[str]]:
    bases: list[dict[str, str]] = []
    external_bases: list[str] = []
    for _, base in types.workspace.base_classes(ref):
        if (
            isinstance(base, SymbolRef)
            and types.workspace.parsed_class(base) is not None
        ):
            bases.append(base.to_json())
        elif isinstance(base, ExternalRef):
            external_bases.append(
                f"{base.module}.{base.name}" if base.name else base.module
            )
    return bases, external_bases


def _field_lists(
    fields: list[tuple[str, PinType, str | None]], is_enum: bool
) -> dict[str, list[list[Any]]]:
    if is_enum:
        return {
            "members": [[name, value or ""] for name, _, value in fields],
            "fields": [],
        }
    return {"fields": [[name, pin.to_json()] for name, pin, _ in fields]}


def _nested_classes(module: ParsedModule, parsed: ParsedClass) -> list[ParsedClass]:
    depth = parsed.qualname.count(".") + 1
    return [
        child
        for q, child in module.classes.items()
        if q.startswith(parsed.qualname + ".") and q.count(".") == depth
    ]


def _fields(
    types: TypeSystem,
    resolver: TypeResolver,
    module: ParsedModule,
    parsed: ParsedClass,
    is_enum: bool,
) -> list[tuple[str, PinType, str | None]]:
    own_type = types.class_type(SymbolRef(module.path, parsed.qualname))
    collector = _FieldCollector(resolver, module, own_type if is_enum else None)
    for statement in parsed.node.body:
        collector.class_statement(statement)
    if not is_enum:
        receiver = module.language.profile.instance_receiver
        for method in _constructor_first(parsed):
            collector.method(method, method.implicit_receiver or receiver)
    return collector.fields()


class _FieldCollector:
    def __init__(
        self, resolver: TypeResolver, module: ParsedModule, enum_type: PinType | None
    ) -> None:
        self.resolver = resolver
        self.module = module
        self.enum_type = enum_type
        self.seen: dict[str, tuple[PinType, str | None]] = {}

    def fields(self) -> list[tuple[str, PinType, str | None]]:
        return [(name, pin, value) for name, (pin, value) in self.seen.items()]

    def class_statement(self, statement: m.Stmt) -> None:
        if isinstance(statement, m.Assign):
            self._class_assign(statement)
        elif isinstance(statement, m.FunctionDef) and statement.function.is_property:
            returns = self.resolver.annotation(statement.function.returns)
            self.seen.setdefault(statement.function.name, (returns, None))

    def method(self, method: m.FunctionDecl, receiver: str) -> None:
        parameter_types = _parameter_types(self.resolver, method)
        for node in m.walk(method):
            if isinstance(node, m.Assign):
                self._method_assign(node, receiver, parameter_types)

    def _class_assign(self, statement: m.Assign) -> None:
        value = _value_text(self.module, statement.value)
        if statement.annotation is not None:
            target = statement.targets[0]
            if isinstance(target, m.Name):
                pin = self.resolver.annotation(statement.annotation)
                self.seen.setdefault(target.id, (pin, value))
            return
        for target in statement.targets:
            if isinstance(target, m.Name) and self._lists_class_name(target.id):
                self.seen.setdefault(
                    target.id, (self._class_value_type(statement), value)
                )

    def _lists_class_name(self, name: str) -> bool:
        if name.startswith("__"):
            return False
        return self.enum_type is not None or not name.startswith("_") or name.isupper()

    def _class_value_type(self, statement: m.Assign) -> PinType:
        if self.enum_type is not None:
            return self.enum_type
        return _value_type(self.resolver, statement.value)

    def _method_assign(
        self, node: m.Assign, receiver: str, parameter_types: dict[str, PinType]
    ) -> None:
        if node.annotation is not None:
            member = _receiver_attribute(node.targets[0], receiver)
            if member is not None:
                pin = self.resolver.annotation(node.annotation)
                self.seen.setdefault(member.attr, (pin, None))
            return
        for target in node.targets:
            member = _receiver_attribute(target, receiver)
            if member is not None:
                pin = _assigned_type(self.resolver, node.value, parameter_types)
                self.seen.setdefault(member.attr, (pin, None))
        for field in receiver_fields(
            node, receiver, self.module, self.resolver.system.workspace
        ):
            pin = self._unpacked_type(field, parameter_types)
            self.seen.setdefault(field.name, (pin, None))

    def _unpacked_type(
        self, field: UnpackedField, parameter_types: dict[str, PinType]
    ) -> PinType:
        if field.annotation is not None:
            part, owner = field.annotation
            return self.resolver.system.resolver(owner).annotation(part)
        if field.value is not None:
            return _assigned_type(self.resolver, field.value, parameter_types)
        return UNKNOWN


def _constructor_first(parsed: ParsedClass) -> list[m.FunctionDecl]:
    methods = [s.function for s in parsed.node.body if isinstance(s, m.FunctionDef)]
    methods.sort(key=lambda method: 0 if method.is_constructor else 1)
    return methods


def _parameter_types(
    resolver: TypeResolver, method: m.FunctionDecl
) -> dict[str, PinType]:
    return {
        parameter.name: resolver.annotation(parameter.annotation)
        for parameter in method.params
        if parameter.annotation is not None
        and parameter.kind in ("positional_only", "positional", "keyword_only")
    }


def _assigned_type(
    resolver: TypeResolver, value: m.Expr | None, parameter_types: dict[str, PinType]
) -> PinType:
    if isinstance(value, m.Name):
        return parameter_types.get(value.id, UNKNOWN)
    return _value_type(resolver, value)


def _bound_type(types: TypeSystem, found: FoundParameter) -> dict[str, Any] | None:
    names = bound_names(found.parameter)
    if not names:
        return None
    resolver = types.resolver(found.module)
    pins = [resolver.named(name) for name in names]
    if len(pins) == 1:
        return pins[0].to_json()
    return PinType(" | ".join(pin.label for pin in pins), "any").to_json()


def _annotations(node: m.FunctionDecl) -> list[m.TypeExpr]:
    found = [
        parameter.annotation
        for parameter in node.params
        if parameter.annotation is not None
    ]
    return [*found, node.returns] if node.returns is not None else found


def _constants(resolver: TypeResolver, module: ParsedModule) -> list[list[Any]]:
    out: list[list[Any]] = []
    for name, statement in module_constants(module):
        pin = (
            resolver.annotation(statement.annotation)
            if statement.annotation is not None
            else _value_type(resolver, statement.value)
        )
        out.append([name, pin.to_json(), _value_text(module, statement.value) or ""])
    return out


def _param(
    resolver: TypeResolver,
    module: ParsedModule,
    function: ParsedFunction,
    parameter: m.Parameter,
    index: int,
) -> list[Any]:
    profile = module.language.profile
    if (
        index == 0
        and function.class_qualname
        and parameter.annotation is None
        and parameter.name in profile.receiver_names
    ):
        owner = resolver.system.class_type(
            SymbolRef(module.path, function.class_qualname)
        )
        pin = (
            owner
            if parameter.name == profile.instance_receiver
            else PinType(f"type[{owner.label}]", "class", ref=owner.ref)
        )
    else:
        pin = resolver.annotation(parameter.annotation)
    entry: list[Any] = [parameter.name, pin.to_json()]
    if parameter.default is not None:
        entry.append(_value_text(module, parameter.default) or "")
    return entry


def _label(resolver: TypeResolver, parameter: m.Parameter) -> str:
    return (
        resolver.annotation(parameter.annotation).label
        if parameter.annotation is not None
        else "Any"
    )


def _value_type(resolver: TypeResolver, value: m.Expr | None) -> PinType:
    profile = resolver.module.language.profile
    if value is None:
        return UNKNOWN
    if isinstance(value, m.Literal):
        return native(literal_type(value.value), profile.literal_labels)
    if isinstance(value, m.Sequence) and value.kind in profile.sequence_kinds:
        label, cat = profile.sequence_kinds[value.kind]
        return PinType(label, cat)
    if isinstance(value, m.Comprehension):
        if value.kind == "dict":
            return PinType(*profile.mapping_kind)
        return PinType(value.kind, "list")
    if isinstance(value, m.Mapping):
        return PinType(*profile.mapping_kind)
    if isinstance(value, m.Template):
        return PinType("str", "str")
    if isinstance(value, m.Call):
        name = m.dotted_name(value.func)
        if name:
            resolved = resolver.named(name)
            if resolved.ref is not None or resolved.cat != "object":
                return resolved
    return UNKNOWN


def _value_text(module: ParsedModule, value: m.Expr | None) -> str | None:
    if value is None:
        return None
    text = module.language.text(value).replace("\n", " ")
    return text if len(text) <= _MAX_VALUE else text[: _MAX_VALUE - 1] + "…"


def _receiver_attribute(node: m.Expr, receiver: str) -> m.Member | None:
    if (
        isinstance(node, m.Member)
        and isinstance(node.value, m.Name)
        and node.value.id == receiver
    ):
        return node
    return None


def _first_paragraph(doc: str | None) -> str | None:
    if not doc:
        return None
    return doc.strip().split("\n\n")[0].replace("\n", " ")[:400]
