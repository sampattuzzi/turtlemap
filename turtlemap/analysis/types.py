import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from turtlemap.analysis import model as m
from turtlemap.analysis.workspace.parsed import (
    ExternalRef,
    ParsedModule,
    SymbolRef,
)
from turtlemap.analysis.workspace.reads import Keys
from turtlemap.analysis.workspace.workspace import Workspace
from turtlemap.languages.language import TypeNames

_MODULE_PREFIX = re.compile(r"\b(?:[A-Za-z_]\w*\.)+([A-Za-z_]\w*)")


@dataclass(frozen=True)
class PinType:
    label: str
    cat: str
    opt: bool = False
    ref: SymbolRef | None = None
    items: SymbolRef | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"label": self.label, "cat": self.cat}
        if self.opt:
            out["opt"] = True
        if self.ref is not None:
            out["ref"] = self.ref.to_json()
        if self.items is not None:
            out["items"] = self.items.to_json()
        return out


UNKNOWN = PinType("Any", "any")


def native(pin: PinType, labels: Mapping[str, str]) -> PinType:
    label = labels.get(pin.label)
    return replace(pin, label=label) if label is not None else pin


def literal_type(value: object) -> PinType:
    if isinstance(value, bool):
        return PinType("bool", "bool")
    if isinstance(value, int):
        return PinType("int", "int")
    if isinstance(value, float):
        return PinType("float", "float")
    if isinstance(value, str):
        return PinType("str", "str")
    if isinstance(value, bytes):
        return PinType("bytes", "bytes")
    if value is None:
        return PinType("None", "none")
    return UNKNOWN


def clean_label(text: str) -> str:
    return _MODULE_PREFIX.sub(r"\1", text).replace("'", "").replace('"', "")


class TypeSystem:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self._categories: dict[SymbolRef, tuple[str, Keys]] = {}
        self.field_cache: dict[
            SymbolRef, tuple[list[tuple[str, PinType, str | None]], Keys]
        ] = {}
        self._computing: set[SymbolRef] = set()

    def resolver(self, module: ParsedModule) -> "TypeResolver":
        return TypeResolver(self, module)

    def class_category(self, ref: SymbolRef) -> str:
        if ref in self._computing and ref not in self._categories:
            return "object"
        return self.workspace.reads.remembered(
            self._categories, ref, lambda: self._guarded_category(ref)
        )

    def _guarded_category(self, ref: SymbolRef) -> str:
        self._computing.add(ref)
        try:
            return self._compute_category(ref)
        finally:
            self._computing.discard(ref)

    def stereotype(self, ref: SymbolRef) -> str | None:
        parsed = self.workspace.parsed_class(ref)
        module = self.workspace.module(ref.path)
        if parsed is None or module is None:
            return None
        if parsed.node.kind != "class":
            return parsed.node.kind
        category = self.class_category(ref)
        if category == "enum":
            return "enum"
        if category == "iface":
            return "protocol"
        if category == "struct":
            return self._struct_stereotype(ref, module.language.profile.types)
        if self._is_exception(ref):
            return "exception"
        if ref.sym.endswith("Mixin"):
            return "mixin"
        return None

    def _struct_stereotype(self, ref: SymbolRef, names: TypeNames) -> str:
        labels = {_base_name(label) for label, _ in self.workspace.base_classes(ref)}
        if labels & names.model_bases:
            return "model"
        if "NamedTuple" in labels:
            return "namedtuple"
        if "TypedDict" in labels:
            return "typeddict"
        return "dataclass"

    def _is_exception(self, ref: SymbolRef) -> bool:
        return any(
            last in ("Exception", "BaseException", "Warning") or last.endswith("Error")
            for ancestor in self.workspace.class_ancestry(ref)
            for last in (
                _base_name(label) for label, _ in self.workspace.base_classes(ancestor)
            )
        )

    def class_type(self, ref: SymbolRef) -> PinType:
        category = self.class_category(ref)
        return PinType(
            ref.sym.rsplit(".", 1)[-1],
            "object" if category == "iface" else category,
            ref=ref,
        )

    def _compute_category(self, ref: SymbolRef) -> str:
        parsed = self.workspace.parsed_class(ref)
        module = self.workspace.module(ref.path)
        if parsed is None or module is None:
            return "object"
        if parsed.node.kind == "interface":
            return "iface"
        if parsed.node.kind == "enum":
            return "enum"
        names = module.language.profile.types
        if _has_struct_decorator(parsed.node, names):
            return "struct"
        return self._category_from_bases(ref, names)

    def _category_from_bases(self, ref: SymbolRef, names: TypeNames) -> str:
        for label, base in self.workspace.base_classes(ref):
            last = _base_name(label)
            if last in names.enum_bases:
                return "enum"
            if last in names.struct_bases:
                return "struct"
            if last in names.interface_bases:
                return "iface"
            if (
                isinstance(base, SymbolRef)
                and self.workspace.parsed_class(base) is not None
            ):
                inherited = self.class_category(base)
                if inherited in ("enum", "struct"):
                    return inherited
        return "object"


class TypeResolver:
    def __init__(self, system: TypeSystem, module: ParsedModule) -> None:
        self.system = system
        self.module = module
        self.names: TypeNames = module.language.profile.types

    def annotation(self, node: m.TypeExpr | None) -> PinType:
        try:
            return self._annotation(node)
        except RecursionError:
            return UNKNOWN

    def named(self, dotted: str) -> PinType:
        last = dotted.rsplit(".", 1)[-1]
        names = self.names
        resolved = self.system.workspace.resolve(self.module, dotted)
        if (
            isinstance(resolved, SymbolRef)
            and self.system.workspace.parsed_class(resolved) is not None
        ):
            return self.system.class_type(resolved)
        if last in names.scalars:
            return PinType(last, names.scalars[last])
        if last in names.lists:
            return PinType(last, "list")
        if last in names.maps:
            return PinType(last, "map")
        if last in names.callables:
            return PinType(last, "callable")
        if last in names.class_types:
            return PinType(last, "class")
        if isinstance(resolved, ExternalRef) and last in names.enum_bases:
            return PinType(last, "enum")
        return PinType(last, "object")

    def label(self, node: m.TypeExpr) -> str:
        return clean_label(self.module.language.text(node))

    def _annotation(self, node: m.TypeExpr | None) -> PinType:
        if node is None:
            return UNKNOWN
        if isinstance(node, m.TypeLiteral):
            if node.value is None:
                return PinType(self.module.language.profile.none_text, "none")
            if isinstance(node.value, str):
                if node.parsed is None:
                    return PinType(node.value, "object")
                return self._annotation(node.parsed)
            return UNKNOWN
        if isinstance(node, m.TypeUnion):
            return self._union(node.members)
        if isinstance(node, m.TypeName):
            if node.args:
                return self._subscripted(node)
            return self.named(node.dotted) if node.dotted else UNKNOWN
        if isinstance(node, m.TypeOther):
            if node.label is not None:
                return PinType(node.label, node.cat) if node.label != "Any" else UNKNOWN
            return PinType(self.label(node), node.cat)
        return UNKNOWN

    def _subscripted(self, node: m.TypeName) -> PinType:
        base = node.dotted
        last = base.rsplit(".", 1)[-1]
        args = node.args
        names = self.names
        label = self.label(node)
        if last in names.optional:
            inner = self._annotation(args[0])
            return replace(inner, opt=True, label=self._optional(inner.label))
        if last in names.union:
            return self._union(args)
        if last in names.transparent:
            return self._annotation(args[0])
        if last in names.awaitables:
            return self._annotation(args[-1])
        if last in names.literal:
            values = [arg.value for arg in args if isinstance(arg, m.TypeLiteral)]
            first = literal_type(values[0]) if values else UNKNOWN
            return PinType(label, first.cat)
        if last in names.guards:
            return PinType("bool", "bool")
        if last in names.class_types:
            return replace(self._annotation(args[0]), cat="class", label=label)
        if last in names.callables:
            return PinType(label, "callable")
        if last in names.lists:
            return PinType(label, "list", items=self._held(args[0]))
        if last in names.maps:
            return PinType(
                label, "map", items=self._held(args[-1]) if len(args) > 1 else None
            )
        named = self.named(base) if base else UNKNOWN
        return replace(named, label=label)

    def _optional(self, label: str) -> str:
        return self.module.language.profile.optional_label.format(label)

    def _held(self, node: m.TypeExpr) -> SymbolRef | None:
        held = self._annotation(node)
        return held.ref or held.items

    def _union(self, members: list[m.TypeExpr]) -> PinType:
        types = [self._annotation(member) for member in members]
        rest = [member for member in types if member.cat != "none"]
        has_none = len(rest) < len(types)
        if not rest:
            return PinType(self.module.language.profile.none_text, "none")
        if len(rest) == 1:
            only = rest[0]
            return replace(
                only,
                opt=has_none or only.opt,
                label=self._optional(only.label) if has_none else only.label,
            )
        categories = {member.cat for member in rest}
        label = " | ".join(member.label for member in rest)
        return PinType(
            self._optional(label) if has_none else label,
            categories.pop() if len(categories) == 1 else "any",
            opt=has_none,
        )


def _base_name(label: str) -> str:
    return label.split("[")[0].rsplit(".", 1)[-1]


def _has_struct_decorator(node: m.ClassDecl, names: TypeNames) -> bool:
    for decorator in node.decorators:
        target = decorator.func if isinstance(decorator, m.Call) else decorator
        name = m.dotted_name(target)
        if name and name.rsplit(".", 1)[-1] in names.struct_decorators:
            return True
    return False
