from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from turtlemap.analysis import model as m
from turtlemap.analysis.symbols import class_fields, module_constants
from turtlemap.analysis.type_parameters import TypeParameters, bound_names
from turtlemap.analysis.types import PinType, TypeResolver, TypeSystem
from turtlemap.analysis.workspace.reads import Keys, ReadLog
from turtlemap.analysis.workspace.parsed import (
    ExternalRef,
    ParsedClass,
    ParsedModule,
    Resolved,
    SymbolRef,
)


@dataclass
class DependencyCollector:
    types: TypeSystem
    edges: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    external_names: set[tuple[str, str | None]] = field(default_factory=set)
    _fields: dict[SymbolRef, tuple[dict[str, PinType], Keys]] = field(
        default_factory=dict
    )
    _own_fields: dict[SymbolRef, tuple[dict[str, PinType], Keys]] = field(
        default_factory=dict
    )
    _constants: dict[str, frozenset[str]] = field(default_factory=dict)
    _constant_ids: dict[tuple[str, str], tuple[str | None, Keys]] = field(
        default_factory=dict
    )
    _generics: TypeParameters | None = None

    @property
    def generics(self) -> TypeParameters:
        if self._generics is None:
            self._generics = TypeParameters(self.types.workspace)
        return self._generics

    def collect(self, module: ParsedModule) -> None:
        resolver = self.types.resolver(module)
        for found in self.generics.declared(module).values():
            for name in bound_names(found.parameter):
                self.link(
                    found.id,
                    self.node_id(self.types.workspace.resolve(module, name)),
                    "bound",
                )
        for parsed in module.classes.values():
            self._collect_class(module, resolver, parsed)
        for function in module.functions.values():
            owner = (
                SymbolRef(module.path, function.class_qualname)
                if function.class_qualname
                else None
            )
            source = f"{'m' if owner else 'fn'}:{module.path}:{function.qualname}"
            CodeDependencies(self, module, resolver, source, owner).collect_function(
                function.node
            )
        for name, statement in module_constants(module):
            CodeDependencies(
                self, module, resolver, f"c:{module.path}:{name}", None
            ).collect_constant(statement)

    def collect_alone(
        self, module: ParsedModule
    ) -> tuple[list[list[Any]], frozenset[tuple[str, str | None]]]:
        self.edges = {}
        self.external_names = set()
        self.collect(module)
        edges = [
            [
                entry["from"],
                entry["to"],
                sorted(entry["kinds"]),
                sorted(entry["labels"]),
            ]
            for entry in self.edges.values()
        ]
        return edges, frozenset(self.external_names)

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

    def constant_id(self, module: ParsedModule, dotted: str) -> str | None:
        return self._reads.remembered(
            self._constant_ids,
            (module.path, dotted),
            lambda: self._find_constant(module, dotted),
        )

    def own_fields(self, ref: SymbolRef) -> dict[str, PinType]:
        return self._reads.remembered(
            self._own_fields,
            ref,
            lambda: {name: pin for name, pin, _ in class_fields(self.types, ref)},
        )

    def fields_of(self, ref: SymbolRef) -> dict[str, PinType]:
        return self._reads.remembered(
            self._fields, ref, lambda: self._merged_fields(ref)
        )

    @property
    def _reads(self) -> ReadLog:
        return self.types.workspace.reads

    def _merged_fields(self, ref: SymbolRef) -> dict[str, PinType]:
        merged: dict[str, PinType] = {}
        for ancestor in reversed(self.types.workspace.class_ancestry(ref)):
            merged.update(self.own_fields(ancestor))
        return merged

    def _find_constant(self, module: ParsedModule, dotted: str) -> str | None:
        head, _, rest = dotted.partition(".")
        if not rest and head in self._constants_in(module):
            return f"c:{module.path}:{head}"
        binding = module.imports.get(head)
        if binding is None:
            if rest:
                return None
            for neighbour in self.types.workspace.script_neighbours(module):
                if head in self._constants_in(neighbour):
                    return f"c:{neighbour.path}:{head}"
            return None
        module_name, _, name = (
            binding.absolute + ("." + rest if rest else "")
        ).rpartition(".")
        path = self.types.workspace.index.find_module(module_name, near=module.path)
        target = self.types.workspace.module(path) if path else None
        if target is None or name not in self._constants_in(target):
            return None
        return f"c:{target.path}:{name}"

    def _constants_in(self, module: ParsedModule) -> frozenset[str]:
        if module.path not in self._constants:
            self._constants[module.path] = frozenset(
                name for name, _ in module_constants(module)
            )
        return self._constants[module.path]

    def _collect_class(
        self, module: ParsedModule, resolver: TypeResolver, parsed: ParsedClass
    ) -> None:
        ref = SymbolRef(module.path, parsed.qualname)
        class_id = f"cls:{module.path}:{parsed.qualname}"
        for found in self.generics.mentioned(module, parsed.node.bases):
            self.link(class_id, found.id, "uses")
        for label, base in self.types.workspace.base_classes(ref):
            target = self.node_id(base)
            last = label.split("[")[0].rsplit(".", 1)[-1]
            is_protocol = last in module.language.profile.types.interface_bases or (
                isinstance(base, SymbolRef)
                and self.types.class_category(base) == "iface"
            )
            self.link(class_id, target, "realizes" if is_protocol else "inherits")
        if self.types.class_category(ref) == "enum":
            return
        for name, pin in self.own_fields(ref).items():
            for held in (pin.ref, pin.items):
                if held is not None:
                    self.link(
                        f"f:{module.path}:{parsed.qualname}.{name}",
                        self.node_id(held),
                        "has",
                        name,
                    )


def edge_table(edges: Iterable[list[Any]]) -> dict[str, Any]:
    ids: dict[str, int] = {}
    rows: list[list[Any]] = []
    for source, target, kinds, labels in edges:
        row: list[Any] = [
            ids.setdefault(source, len(ids)),
            ids.setdefault(target, len(ids)),
            ",".join(sorted(shown_kinds(kinds))),
        ]
        if labels:
            row.append(",".join(labels))
        rows.append(row)
    return {"ids": list(ids), "rows": rows}


def shown_kinds(kinds: Iterable[str]) -> frozenset[str]:
    shown = set(kinds)
    if shown & {"calls", "creates"}:
        shown.discard("uses")
    return frozenset(shown)


class CodeDependencies:
    def __init__(
        self,
        collector: DependencyCollector,
        module: ParsedModule,
        resolver: TypeResolver,
        source: str,
        owner: SymbolRef | None,
    ) -> None:
        self.collector = collector
        self.module = module
        self.resolver = resolver
        self.source = source
        self.owner = owner
        self.local_types: dict[str, PinType] = {}
        self.locals: frozenset[str] = frozenset()
        self._called: set[int] = set()

    def collect_constant(self, statement: m.Assign) -> None:
        if statement.annotation is not None:
            self._use(self.resolver.annotation(statement.annotation))
        if statement.value is not None:
            for child in m.walk(statement.value):
                self._visit(child)

    def collect_function(self, node: m.FunctionDecl) -> None:
        profile = self.module.language.profile
        self.locals = m.bound_names(node) - {
            name
            for child in m.walk(node)
            if isinstance(child, m.Global)
            for name in child.names
        }
        for parameter in node.params:
            if parameter.annotation is not None and parameter.kind in (
                "positional_only",
                "positional",
                "keyword_only",
            ):
                pin = self.resolver.annotation(parameter.annotation)
                self.local_types[parameter.name] = pin
                self._use(pin)
        regular = [p for p in node.params if p.kind == "positional"]
        if (
            self.owner is not None
            and regular
            and regular[0].name in profile.receiver_names
        ):
            self.local_types[regular[0].name] = self.resolver.system.class_type(
                self.owner
            )
        if self.owner is not None and node.implicit_receiver is not None:
            self.local_types[node.implicit_receiver] = self.resolver.system.class_type(
                self.owner
            )
        if node.returns is not None:
            self._use(self.resolver.annotation(node.returns))
        signature = [
            *(p.annotation for p in node.params if p.annotation is not None),
            *([node.returns] if node.returns is not None else []),
        ]
        for found in self.collector.generics.mentioned(self.module, signature):
            self.collector.link(self.source, found.id, "uses")
        outer = self.locals
        for statement in node.body:
            pending: deque[tuple[m.Node, frozenset[str]]] = deque([(statement, outer)])
            while pending:
                current, scope = pending.popleft()
                self.locals = scope
                self._visit(current)
                inner = scope | _scope_names(current)
                pending.extend((child, inner) for child in m.children(current))

    def _visit(self, node: m.Node) -> None:
        if isinstance(node, m.Assign):
            self._track_assignment(node)
        elif isinstance(node, m.For):
            self._track_element(node.target, node.iter)
        elif isinstance(node, m.Comprehension):
            for clause in node.clauses:
                self._track_element(clause.target, clause.iterable)
        elif isinstance(node, m.Call):
            self._call(node)
        elif isinstance(node, m.Member):
            self._field_access(node)
            self._constant_access(node)
            self._property_access(node)
            self._method_reference(node)
        elif isinstance(node, m.TypeName):
            self._type_name(node)
        elif (
            isinstance(node, m.Name)
            and not node.store
            and node.id not in self.local_types
            and node.id not in self.locals
        ):
            constant = self.collector.constant_id(self.module, node.id)
            if constant is not None:
                self.collector.link(self.source, constant, "reads")
                return
            resolved = self.collector.types.workspace.resolve(self.module, node.id)
            if isinstance(resolved, SymbolRef):
                target = self.collector.node_id(resolved)
                self.collector.link(self.source, target, "uses")

    def _type_name(self, node: m.TypeName) -> None:
        if node.dotted.split(".")[0] in self.local_types:
            return
        parameter = self.collector.generics.find(self.module, node.dotted)
        if parameter is not None:
            self.collector.link(self.source, parameter.id, "uses")
            return
        constant = self.collector.constant_id(
            self.module, node.dotted
        ) or self.collector.constant_id(self.module, node.dotted.split(".")[0])
        if constant is not None:
            self.collector.link(self.source, constant, "reads")
            return
        resolved = self.collector.types.workspace.resolve(self.module, node.dotted)
        if isinstance(resolved, SymbolRef):
            target = self.collector.node_id(resolved)
            self.collector.link(self.source, target, "uses")

    def _call(self, call: m.Call) -> None:
        func = call.func
        self._called.add(id(func))
        resolved = self._callee(func)
        target = self.collector.node_id(resolved)
        if target is None:
            return
        kind = "creates" if target.startswith("cls:") else "calls"
        self.collector.link(self.source, target, kind)

    def _callee(self, func: m.Expr) -> Resolved | None:
        workspace = self.collector.types.workspace
        if isinstance(func, m.Name):
            if func.id in self.local_types or func.id in self.locals:
                return None
            return workspace.resolve(self.module, func.id)
        if not isinstance(func, m.Member):
            return None
        receiver = self._type_of(func.value)
        if (
            receiver is not None
            and receiver.ref is not None
            and workspace.parsed_class(receiver.ref) is not None
        ):
            return workspace.find_method(receiver.ref, func.attr)
        if self._calls_super(func.value):
            return self._inherited_method(func.attr)
        dotted = m.dotted_name(func)
        if dotted is None:
            return None
        head = dotted.split(".")[0]
        if head in self.local_types or head in self.locals:
            return None
        return workspace.resolve(self.module, dotted)

    def _calls_super(self, value: m.Expr) -> bool:
        return (
            isinstance(value, m.Call)
            and isinstance(value.func, m.Name)
            and value.func.id == self.module.language.profile.super_name
            and self.owner is not None
        )

    def _inherited_method(self, name: str) -> Resolved | None:
        workspace = self.collector.types.workspace
        assert self.owner is not None
        for _, base in workspace.base_classes(self.owner):
            if isinstance(base, SymbolRef):
                found = workspace.find_method(base, name)
                if found is not None:
                    return found
        return None

    def _type_of(self, node: m.Expr) -> PinType | None:
        if isinstance(node, m.Name):
            return self.local_types.get(node.id)
        if isinstance(node, m.Member):
            base = self._type_of(node.value)
            if base is not None and base.ref is not None:
                field_type = self.collector.fields_of(base.ref).get(node.attr)
                getter = self._property(node)
                return (
                    field_type
                    if field_type is not None or getter is None
                    else self._returned_by(getter)
                )
        if isinstance(node, m.Call):
            return self._returned_type(node)
        if isinstance(node, m.Subscript):
            container = self._type_of(node.value)
            if container is None or isinstance(node.index, m.Slice):
                return container
            return self._element_of(container)
        return None

    def _element_of(self, container: PinType | None) -> PinType | None:
        if container is None or container.items is None:
            return None
        return self.collector.types.class_type(container.items)

    def _track_element(self, target: m.Expr, iterable: m.Expr) -> None:
        element = self._element_of(self._type_of(iterable))
        if element is not None and isinstance(target, m.Name):
            self.local_types[target.id] = element

    def _track_assignment(self, node: m.Assign) -> None:
        if node.annotation is not None:
            pin: PinType | None = self.resolver.annotation(node.annotation)
        else:
            pin = self._value_type(node.value)
        if pin is None:
            return
        for target in node.targets:
            if isinstance(target, m.Name):
                self.local_types[target.id] = pin

    def _value_type(self, value: m.Expr | None) -> PinType | None:
        return self._type_of(value) if value is not None else None

    def _returned_type(self, call: m.Call) -> PinType | None:
        resolved = self._callee(call.func)
        workspace = self.collector.types.workspace
        if isinstance(resolved, SymbolRef):
            if workspace.parsed_class(resolved) is not None:
                return self.collector.types.class_type(resolved)
            return self._returned_by(resolved)
        return None

    def _returned_by(self, ref: SymbolRef) -> PinType | None:
        workspace = self.collector.types.workspace
        function = workspace.parsed_function(ref)
        target_module = workspace.module(ref.path)
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

    def _field_access(self, node: m.Member) -> None:
        receiver = self._type_of(node.value)
        if receiver is None or receiver.ref is None:
            return
        if node.attr not in self.collector.fields_of(receiver.ref):
            return
        holder = self._field_owner(receiver.ref, node.attr)
        kind = "writes" if node.store else "reads"
        self.collector.link(
            self.source, f"f:{holder.path}:{holder.sym}.{node.attr}", kind
        )

    def _method_reference(self, node: m.Member) -> None:
        if node.store or id(node) in self._called:
            return
        receiver = self._type_of(node.value)
        workspace = self.collector.types.workspace
        if receiver is None or receiver.ref is None:
            return
        if workspace.parsed_class(receiver.ref) is None:
            return
        found = workspace.find_method(receiver.ref, node.attr)
        if found is not None and not workspace.reads_as_property(found):
            self.collector.link(self.source, self.collector.node_id(found), "uses")

    def _property_access(self, node: m.Member) -> None:
        if node.store:
            return
        getter = self._property(node)
        if getter is not None:
            self.collector.link(self.source, self.collector.node_id(getter), "calls")

    def _property(self, node: m.Member) -> SymbolRef | None:
        workspace = self.collector.types.workspace
        receiver = self._type_of(node.value)
        if receiver is None or receiver.ref is None:
            return None
        if workspace.parsed_class(receiver.ref) is None:
            return None
        found = workspace.find_method(receiver.ref, node.attr)
        return (
            found if found is not None and workspace.reads_as_property(found) else None
        )

    def _constant_access(self, node: m.Member) -> None:
        if node.store:
            return
        dotted = m.dotted_name(node)
        if dotted is None or dotted.split(".")[0] in self.local_types:
            return
        self.collector.link(
            self.source, self.collector.constant_id(self.module, dotted), "reads"
        )

    def _field_owner(self, holder: SymbolRef, attr: str) -> SymbolRef:
        for ancestor in self.collector.types.workspace.class_ancestry(holder):
            if attr in self.collector.own_fields(ancestor):
                return ancestor
        return holder


def _scope_names(node: m.Node) -> frozenset[str]:
    if isinstance(node, m.FunctionDef):
        return m.bound_names(node.function)
    if isinstance(node, m.Function):
        return m.bound_names(node)
    if isinstance(node, m.Comprehension):
        return frozenset(node.bound)
    return frozenset()
