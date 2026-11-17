import ast
from typing import Any

from code_blueprints.analysis.types import (
    PinType,
    TypeResolver,
    TypeSystem,
    UNKNOWN,
    literal_type,
)
from code_blueprints.analysis.workspace import (
    ExternalRef,
    ParsedClass,
    ParsedFunction,
    ParsedModule,
    SymbolRef,
    dotted_name,
    import_from_base,
    library_of,
)

_PROPERTY_DECORATORS = frozenset(
    {"property", "cached_property", "functools.cached_property"}
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
    return {
        "path": module.path,
        "name": module.name,
        "doc": _first_paragraph(ast.get_docstring(module.tree)),
        "symbols": symbols,
        "constants": _constants(resolver, module),
        "imports": module_imports(types, module),
    }


def function_summary(
    resolver: TypeResolver, module: ParsedModule, function: ParsedFunction
) -> dict[str, Any]:
    node = function.node
    summary: dict[str, Any] = {
        "kind": "function",
        "name": node.name,
        "qual": function.qualname,
        "line": node.lineno,
        "end": node.end_lineno or node.lineno,
        "params": parameters(resolver, module, function),
        "returns": (
            resolver.annotation(node.returns).to_json()
            if node.returns is not None
            else (
                PinType("None", "none").to_json()
                if node.name == "__init__"
                else UNKNOWN.to_json()
            )
        ),
    }
    if isinstance(node, ast.AsyncFunctionDef):
        summary["async"] = True
    doc = _first_paragraph(ast.get_docstring(node))
    if doc:
        summary["doc"] = doc
    decorators = [ast.unparse(d) for d in node.decorator_list]
    if decorators:
        summary["decorators"] = decorators
    return summary


def parameters(
    resolver: TypeResolver, module: ParsedModule, function: ParsedFunction
) -> list[list[Any]]:
    args = function.node.args
    positional = [*args.posonlyargs, *args.args]
    defaults: list[ast.expr | None] = [None] * (
        len(positional) - len(args.defaults)
    ) + list(args.defaults)
    out: list[list[Any]] = []
    for index, (arg, default) in enumerate(zip(positional, defaults)):
        out.append(_param(resolver, module, function, arg, default, index))
    if args.vararg is not None:
        out.append(
            [
                f"*{args.vararg.arg}",
                PinType(
                    f"tuple[{_label(resolver, args.vararg)}, ...]", "list"
                ).to_json(),
            ]
        )
    for arg, kw_default in zip(args.kwonlyargs, args.kw_defaults):
        out.append(_param(resolver, module, function, arg, kw_default, -1))
    if args.kwarg is not None:
        out.append(
            [
                f"**{args.kwarg.arg}",
                PinType(f"dict[str, {_label(resolver, args.kwarg)}]", "map").to_json(),
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
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                path = workspace.find_module(alias.name, near=module.path)
                if path is not None or not workspace.is_package(alias.name):
                    add(alias.name, path, None)
            continue
        base = import_from_base(module, statement)
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
            if path is None and (statement.level > 0 or workspace.is_package(base)):
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


def module_constants(
    module: ParsedModule,
) -> list[tuple[str, ast.AnnAssign | ast.Assign]]:
    found: list[tuple[str, ast.AnnAssign | ast.Assign]] = []
    for statement in module.tree.body:
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
        ):
            found.append((statement.target.id, statement))
        elif (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and _is_constant_name(statement.targets[0].id)
        ):
            found.append((statement.targets[0].id, statement))
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
        "line": parsed.node.lineno,
        "end": parsed.node.end_lineno or parsed.node.lineno,
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
    doc = _first_paragraph(ast.get_docstring(parsed.node))
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
    for statement in parsed.node.body:
        if isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            name = statement.target.id
            seen.setdefault(
                name,
                (
                    resolver.annotation(statement.annotation),
                    _value_text(statement.value),
                ),
            )
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("__"):
                    if is_enum:
                        seen.setdefault(
                            target.id, (own_type, _value_text(statement.value))
                        )
                    elif not target.id.startswith("_") or target.id.isupper():
                        seen.setdefault(
                            target.id,
                            (
                                _value_type(resolver, statement.value),
                                _value_text(statement.value),
                            ),
                        )
        elif isinstance(
            statement, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and _is_property(statement):
            seen.setdefault(
                statement.name, (resolver.annotation(statement.returns), None)
            )
    if is_enum:
        return [(name, pin, value) for name, (pin, value) in seen.items()]
    methods = [
        s
        for s in parsed.node.body
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    methods.sort(key=lambda m: 0 if m.name == "__init__" else 1)
    for method in methods:
        param_types = {
            arg.arg: resolver.annotation(arg.annotation)
            for arg in [
                *method.args.posonlyargs,
                *method.args.args,
                *method.args.kwonlyargs,
            ]
            if arg.annotation is not None
        }
        for node in ast.walk(method):
            if isinstance(node, ast.AnnAssign) and _is_self_attribute(node.target):
                assert isinstance(node.target, ast.Attribute)
                seen.setdefault(
                    node.target.attr, (resolver.annotation(node.annotation), None)
                )
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if _is_self_attribute(target):
                        assert isinstance(target, ast.Attribute)
                        value = node.value
                        pin = (
                            param_types.get(value.id, UNKNOWN)
                            if isinstance(value, ast.Name)
                            else _value_type(resolver, value)
                        )
                        seen.setdefault(target.attr, (pin, None))
    return [(name, pin, value) for name, (pin, value) in seen.items()]


def _constants(resolver: TypeResolver, module: ParsedModule) -> list[list[Any]]:
    out: list[list[Any]] = []
    for name, statement in module_constants(module):
        pin = (
            resolver.annotation(statement.annotation)
            if isinstance(statement, ast.AnnAssign)
            else _value_type(resolver, statement.value)
        )
        out.append([name, pin.to_json(), _value_text(statement.value) or ""])
    return out


def _param(
    resolver: TypeResolver,
    module: ParsedModule,
    function: ParsedFunction,
    arg: ast.arg,
    default: ast.expr | None,
    index: int,
) -> list[Any]:
    if (
        index == 0
        and function.class_qualname
        and arg.annotation is None
        and arg.arg in ("self", "cls")
    ):
        owner = resolver.system.class_type(
            SymbolRef(module.path, function.class_qualname)
        )
        pin = (
            owner
            if arg.arg == "self"
            else PinType(f"type[{owner.label}]", "class", ref=owner.ref)
        )
    else:
        pin = resolver.annotation(arg.annotation)
    entry: list[Any] = [arg.arg, pin.to_json()]
    if default is not None:
        entry.append(_value_text(default) or "")
    return entry


def _label(resolver: TypeResolver, arg: ast.arg) -> str:
    return (
        resolver.annotation(arg.annotation).label
        if arg.annotation is not None
        else "Any"
    )


def _value_type(resolver: TypeResolver, value: ast.expr | None) -> PinType:
    if value is None:
        return UNKNOWN
    if isinstance(value, ast.Constant):
        return literal_type(value.value)
    if isinstance(
        value,
        (ast.List, ast.Tuple, ast.Set, ast.ListComp, ast.SetComp, ast.GeneratorExp),
    ):
        return PinType(
            type(value)
            .__name__.lower()
            .replace("comp", "")
            .replace("generatorexp", "generator"),
            "list",
        )
    if isinstance(value, (ast.Dict, ast.DictComp)):
        return PinType("dict", "map")
    if isinstance(value, ast.JoinedStr):
        return PinType("str", "str")
    if isinstance(value, ast.Call):
        name = dotted_name(value.func)
        if name:
            resolved = resolver.named(name)
            if resolved.ref is not None or resolved.cat != "object":
                return resolved
    return UNKNOWN


def _value_text(value: ast.expr | None) -> str | None:
    if value is None:
        return None
    text = ast.unparse(value).replace("\n", " ")
    return text if len(text) <= _MAX_VALUE else text[: _MAX_VALUE - 1] + "…"


def _is_self_attribute(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def _is_property(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(dotted_name(d) in _PROPERTY_DECORATORS for d in node.decorator_list)


def _first_paragraph(doc: str | None) -> str | None:
    if not doc:
        return None
    return doc.strip().split("\n\n")[0].replace("\n", " ")[:400]


def _is_constant_name(name: str) -> bool:
    bare = name.lstrip("_")
    return bool(bare) and bare.isupper()
