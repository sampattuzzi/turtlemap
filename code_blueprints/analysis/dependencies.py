import ast
from dataclasses import dataclass, field
from typing import Any

from code_blueprints.analysis.symbols import class_fields
from code_blueprints.analysis.types import PinType, TypeResolver, TypeSystem
from code_blueprints.analysis.workspace import (
    ExternalRef,
    ParsedClass,
    ParsedFunction,
    ParsedModule,
    Resolved,
    SymbolRef,
    dotted_name,
)

_PROTOCOL_NAMES = frozenset({"Protocol", "ABC"})


@dataclass
class DependencyCollector:
    types: TypeSystem
    edges: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    external_names: set[tuple[str, str | None]] = field(default_factory=set)
    _fields: dict[SymbolRef, dict[str, PinType]] = field(default_factory=dict)
    _own_fields: dict[SymbolRef, dict[str, PinType]] = field(default_factory=dict)

    def collect(self, module: ParsedModule) -> None:
        resolver = self.types.resolver(module)
        for parsed in module.classes.values():
            self._collect_class(module, resolver, parsed)
        for function in module.functions.values():
            owner = (
                SymbolRef(module.path, function.class_qualname)
                if function.class_qualname
                else None
            )
            FunctionDependencies(self, module, resolver, function, owner).collect()

    def result(self) -> dict[str, Any]:
        ids: dict[str, int] = {}
        rows: list[list[Any]] = []
        for entry in self.edges.values():
            kinds = set(entry["kinds"])
            if kinds & {"calls", "creates"}:
                kinds.discard("uses")
            row: list[Any] = [
                ids.setdefault(entry["from"], len(ids)),
                ids.setdefault(entry["to"], len(ids)),
                ",".join(sorted(kinds)),
            ]
            if entry["labels"]:
                row.append(",".join(sorted(entry["labels"])))
            rows.append(row)
        return {"ids": list(ids), "rows": rows}

    def link(
        self, source: str, target: str | None, kind: str, label: str | None = None
    ) -> None:
        if target is None or source == target:
            return
        entry = self.edges.setdefault(
            (source, target),
            {"from": source, "to": target, "kinds": set(), "labels": set()},
        )
        entry["kinds"].add(kind)
        if label:
            entry["labels"].add(label)

    def node_id(self, resolved: Resolved | None) -> str | None:
        workspace = self.types.workspace
        if isinstance(resolved, SymbolRef):
            if workspace.parsed_class(resolved) is not None:
                return f"cls:{resolved.path}:{resolved.sym}"
            function = workspace.parsed_function(resolved)
            if function is not None:
                return f"{'m' if function.class_qualname else 'fn'}:{resolved.path}:{resolved.sym}"
            return None
        if isinstance(resolved, ExternalRef):
            self.external_names.add((resolved.module, resolved.name))
            return (
                f"libn:{resolved.module}.{resolved.name}"
                if resolved.name
                else f"libmod:{resolved.module}"
            )
        return None

    def own_fields(self, ref: SymbolRef) -> dict[str, PinType]:
        if ref not in self._own_fields:
            self._own_fields[ref] = {
                name: pin for name, pin, _ in class_fields(self.types, ref)
            }
        return self._own_fields[ref]

    def fields_of(self, ref: SymbolRef) -> dict[str, PinType]:
        if ref not in self._fields:
            merged: dict[str, PinType] = {}
            for ancestor in reversed(self.types.workspace.class_ancestry(ref)):
                merged.update(self.own_fields(ancestor))
            self._fields[ref] = merged
        return self._fields[ref]

    def _collect_class(
        self, module: ParsedModule, resolver: TypeResolver, parsed: ParsedClass
    ) -> None:
        ref = SymbolRef(module.path, parsed.qualname)
        class_id = f"cls:{module.path}:{parsed.qualname}"
        for label, base in self.types.workspace.base_classes(ref):
            target = self.node_id(base)
            last = label.split("[")[0].rsplit(".", 1)[-1]
            is_protocol = last in _PROTOCOL_NAMES or (
                isinstance(base, SymbolRef)
                and self.types.class_category(base) == "iface"
            )
            self.link(class_id, target, "realizes" if is_protocol else "inherits")
        if self.types.class_category(ref) == "enum":
            return
        for name, pin in self.own_fields(ref).items():
            if pin.ref is not None:
                self.link(
                    f"f:{module.path}:{parsed.qualname}.{name}",
                    self.node_id(pin.ref),
                    "has",
                    name,
                )


class FunctionDependencies:
    def __init__(
        self,
        collector: DependencyCollector,
        module: ParsedModule,
        resolver: TypeResolver,
        function: ParsedFunction,
        owner: SymbolRef | None,
    ) -> None:
        self.collector = collector
        self.module = module
        self.resolver = resolver
        self.function = function
        self.owner = owner
        self.source = f"{'m' if owner else 'fn'}:{module.path}:{function.qualname}"
        self.local_types: dict[str, PinType] = {}

    def collect(self) -> None:
        node = self.function.node
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            if arg.annotation is not None:
                pin = self.resolver.annotation(arg.annotation)
                self.local_types[arg.arg] = pin
                self._use(pin)
        if (
            self.owner is not None
            and node.args.args
            and node.args.args[0].arg in ("self", "cls")
        ):
            self.local_types[node.args.args[0].arg] = self.resolver.system.class_type(
                self.owner
            )
        if node.returns is not None:
            self._use(self.resolver.annotation(node.returns))
        for statement in node.body:
            for child in ast.walk(statement):
                self._visit(child)

    def _visit(self, node: ast.AST) -> None:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            self._track_assignment(node)
        elif isinstance(node, ast.Call):
            self._call(node)
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and self.owner is not None
        ):
            if node.attr in self.collector.fields_of(self.owner):
                kind = "writes" if isinstance(node.ctx, ast.Store) else "reads"
                holder = self._field_owner(node.attr)
                self.collector.link(
                    self.source, f"f:{holder.path}:{holder.sym}.{node.attr}", kind
                )
        elif (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id not in self.local_types
        ):
            resolved = self.collector.types.workspace.resolve(self.module, node.id)
            if isinstance(resolved, SymbolRef):
                target = self.collector.node_id(resolved)
                self.collector.link(self.source, target, "uses")

    def _call(self, call: ast.Call) -> None:
        func = call.func
        resolved = self._callee(func)
        target = self.collector.node_id(resolved)
        if target is None:
            return
        kind = "creates" if target.startswith("cls:") else "calls"
        self.collector.link(self.source, target, kind)

    def _callee(self, func: ast.expr) -> Resolved | None:
        workspace = self.collector.types.workspace
        if isinstance(func, ast.Name):
            if func.id in self.local_types:
                return None
            return workspace.resolve(self.module, func.id)
        if not isinstance(func, ast.Attribute):
            return None
        receiver = self._type_of(func.value)
        if (
            receiver is not None
            and receiver.ref is not None
            and workspace.parsed_class(receiver.ref) is not None
        ):
            return workspace.find_method(receiver.ref, func.attr)
        if (
            isinstance(func.value, ast.Call)
            and isinstance(func.value.func, ast.Name)
            and func.value.func.id == "super"
            and self.owner is not None
        ):
            for _, base in workspace.base_classes(self.owner):
                if isinstance(base, SymbolRef):
                    found = workspace.find_method(base, func.attr)
                    if found is not None:
                        return found
            return None
        dotted = dotted_name(func)
        if dotted is None or dotted.split(".")[0] in self.local_types:
            return None
        return workspace.resolve(self.module, dotted)

    def _type_of(self, node: ast.expr) -> PinType | None:
        if isinstance(node, ast.Name):
            return self.local_types.get(node.id)
        if isinstance(node, ast.Attribute):
            base = self._type_of(node.value)
            if base is not None and base.ref is not None:
                return self.collector.fields_of(base.ref).get(node.attr)
        return None

    def _track_assignment(self, node: ast.Assign | ast.AnnAssign) -> None:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if isinstance(node, ast.AnnAssign):
            pin: PinType | None = self.resolver.annotation(node.annotation)
        else:
            pin = self._value_type(node.value)
        if pin is None:
            return
        for target in targets:
            if isinstance(target, ast.Name):
                self.local_types[target.id] = pin

    def _value_type(self, value: ast.expr | None) -> PinType | None:
        if not isinstance(value, ast.Call):
            return self._type_of(value) if value is not None else None
        resolved = self._callee(value.func)
        workspace = self.collector.types.workspace
        if isinstance(resolved, SymbolRef):
            if workspace.parsed_class(resolved) is not None:
                return self.collector.types.class_type(resolved)
            function = workspace.parsed_function(resolved)
            target_module = workspace.module(resolved.path)
            if (
                function is not None
                and target_module is not None
                and function.node.returns is not None
            ):
                return self.collector.types.resolver(target_module).annotation(
                    function.node.returns
                )
        return None

    def _use(self, pin: PinType) -> None:
        if pin.ref is not None:
            self.collector.link(self.source, self.collector.node_id(pin.ref), "uses")

    def _field_owner(self, attr: str) -> SymbolRef:
        assert self.owner is not None
        for ancestor in self.collector.types.workspace.class_ancestry(self.owner):
            if attr in self.collector.own_fields(ancestor):
                return ancestor
        return self.owner
