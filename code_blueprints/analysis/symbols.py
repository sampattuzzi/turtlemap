from typing import Any

from code_blueprints.analysis import model as m
from code_blueprints.analysis.types import (
    PinType,
    TypeResolver,
    TypeSystem,
    UNKNOWN,
    literal_type,
    native,
)
from code_blueprints.analysis.workspace import (
    ExternalRef,
    ParsedClass,
    ParsedFunction,
    ParsedModule,
    SymbolRef,
    library_of,
)

_MAX_VALUE = 48


def module_summary(types: TypeSystem, module: ParsedModule) -> dict[str, Any]:
    resolver = types.resolver(module)
    symbols: list[dict[str, Any]] = []
    for name, qualname in module.top_level.items():
        if qualname in module.classes:
            symbols.extend(
                _class_summaries(types, resolver, module, module.classes[qualname])
            )
        elif qualname in module.functions:
            symbols.append(
                function_summary(resolver, module, module.functions[qualname])
            )
    symbols.sort(key=lambda s: int(s["line"]))
    summary: dict[str, Any] = {
        "path": module.path,
        "name": module.name,
        "doc": _first_paragraph(module.code.doc),
        "symbols": symbols,
        "constants": _constants(resolver, module),
        "imports": module_imports(types, module),
    }
    if module.language.name != "python":
        summary["lang"] = module.language.name
    return summary


def function_summary(
    resolver: TypeResolver, module: ParsedModule, function: ParsedFunction
) -> dict[str, Any]:
    node = function.node
    profile = module.language.profile
    summary: dict[str, Any] = {
        "kind": "function",
        "name": node.name,
        "qual": function.qualname,
        "line": node.line,
        "end": node.end_line or node.line,
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


def module_imports(types: TypeSystem, module: ParsedModule) -> list[dict[str, Any]]:
    workspace = types.workspace
    grouped: dict[str, dict[str, Any]] = {}

    def add(name: str, path: str | None, imported: str | None) -> None:
        entry = grouped.setdefault(name, {"module": name, "path": path, "names": []})
        if imported and imported not in entry["names"]:
            entry["names"].append(imported)

    for statement in module.import_statements:
        if statement.whole:
            for alias in statement.names:
                path = workspace.find_module(alias.name, near=module.path)
                if path is not None or not workspace.is_package(
                    alias.name, near=module.path
                ):
                    add(alias.name, path, None)
            continue
        base = statement.module
        if base is None:
            continue
        for alias in statement.names:
            if alias.name == "*":
                continue
            submodule = (
                workspace.find_module(f"{base}.{alias.name}", near=module.path)
                if base
                else None
            )
            if submodule is not None:
                add(f"{base}.{alias.name}", submodule, None)
                continue
            path = workspace.find_module(base, near=module.path) if base else None
            if path is None and (
                statement.level > 0 or workspace.is_package(base, near=module.path)
            ):
                resolved = workspace.resolve_absolute(
                    f"{base}.{alias.name}", near=module.path
                )
                if isinstance(resolved, SymbolRef):
                    add(
                        module_of_path(types, resolved.path),
                        resolved.path,
                        resolved.sym.split(".")[0],
                    )
                continue
            add(base, path, alias.name)
    out = list(grouped.values())
    for entry in out:
        if entry["path"] is None:
            entry["lib"] = library_of(entry["module"])
    return out


def module_of_path(types: TypeSystem, path: str) -> str:
    module = types.workspace.module(path)
    return module.name if module else path


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
    types: TypeSystem, resolver: TypeResolver, module: ParsedModule, parsed: ParsedClass
) -> list[dict[str, Any]]:
    ref = SymbolRef(module.path, parsed.qualname)
    category = types.class_category(ref)
    is_enum = category == "enum"
    bases: list[dict[str, str]] = []
    external_bases: list[str] = []
    for label, base in types.workspace.base_classes(ref):
        if (
            isinstance(base, SymbolRef)
            and types.workspace.parsed_class(base) is not None
        ):
            bases.append(base.to_json())
        elif isinstance(base, ExternalRef):
            external_bases.append(
                f"{base.module}.{base.name}" if base.name else base.module
            )
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
            function_summary(resolver, module, module.functions[q])
            for q in parsed.methods.values()
            if q in module.functions
        ],
    }
    stereo = types.stereotype(ref)
    if stereo:
        summary["stereo"] = stereo
    if external_bases:
        summary["extBases"] = external_bases
    if is_enum:
        summary["members"] = [[name, value or ""] for name, _, value in fields]
        summary["fields"] = []
    else:
        summary["fields"] = [[name, pin.to_json()] for name, pin, _ in fields]
    doc = _first_paragraph(parsed.node.doc)
    if doc:
        summary["doc"] = doc
    nested = [
        child
        for q, child in module.classes.items()
        if q.startswith(parsed.qualname + ".")
        and q.count(".") == parsed.qualname.count(".") + 1
    ]
    out = [summary]
    for child in nested:
        out.extend(_class_summaries(types, resolver, module, child))
    return out


def _fields(
    types: TypeSystem,
    resolver: TypeResolver,
    module: ParsedModule,
    parsed: ParsedClass,
    is_enum: bool,
) -> list[tuple[str, PinType, str | None]]:
    seen: dict[str, tuple[PinType, str | None]] = {}
    own_type = types.class_type(SymbolRef(module.path, parsed.qualname))
    receiver = module.language.profile.instance_receiver
    for statement in parsed.node.body:
        if (
            isinstance(statement, m.Assign)
            and statement.annotation is not None
            and isinstance(statement.targets[0], m.Name)
        ):
            name = statement.targets[0].id
            seen.setdefault(
                name,
                (
                    resolver.annotation(statement.annotation),
                    _value_text(module, statement.value),
                ),
            )
        elif isinstance(statement, m.Assign) and statement.annotation is None:
            for target in statement.targets:
                if isinstance(target, m.Name) and not target.id.startswith("__"):
                    if is_enum:
                        seen.setdefault(
                            target.id, (own_type, _value_text(module, statement.value))
                        )
                    elif not target.id.startswith("_") or target.id.isupper():
                        seen.setdefault(
                            target.id,
                            (
                                _value_type(resolver, statement.value),
                                _value_text(module, statement.value),
                            ),
                        )
        elif isinstance(statement, m.FunctionDef) and statement.function.is_property:
            seen.setdefault(
                statement.function.name,
                (resolver.annotation(statement.function.returns), None),
            )
    if is_enum:
        return [(name, pin, value) for name, (pin, value) in seen.items()]
    methods = [s.function for s in parsed.node.body if isinstance(s, m.FunctionDef)]
    methods.sort(key=lambda method: 0 if method.is_constructor else 1)
    for method in methods:
        param_types = {
            parameter.name: resolver.annotation(parameter.annotation)
            for parameter in method.params
            if parameter.annotation is not None
            and parameter.kind in ("positional_only", "positional", "keyword_only")
        }
        receiver_name = method.implicit_receiver or receiver
        for node in m.walk(method):
            if not isinstance(node, m.Assign):
                continue
            if node.annotation is not None:
                target = node.targets[0]
                if _is_receiver_attribute(target, receiver_name):
                    assert isinstance(target, m.Member)
                    seen.setdefault(
                        target.attr, (resolver.annotation(node.annotation), None)
                    )
                continue
            for target in node.targets:
                if _is_receiver_attribute(target, receiver_name):
                    assert isinstance(target, m.Member)
                    value = node.value
                    pin = (
                        param_types.get(value.id, UNKNOWN)
                        if isinstance(value, m.Name)
                        else _value_type(resolver, value)
                    )
                    seen.setdefault(target.attr, (pin, None))
    return [(name, pin, value) for name, (pin, value) in seen.items()]


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


def _is_receiver_attribute(node: m.Expr, receiver: str) -> bool:
    return (
        isinstance(node, m.Member)
        and isinstance(node.value, m.Name)
        and node.value.id == receiver
    )


def _first_paragraph(doc: str | None) -> str | None:
    if not doc:
        return None
    return doc.strip().split("\n\n")[0].replace("\n", " ")[:400]
