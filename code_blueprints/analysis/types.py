import ast
import re
from dataclasses import dataclass, replace
from typing import Any

from code_blueprints.analysis.workspace import (
    ExternalRef,
    ParsedModule,
    SymbolRef,
    Workspace,
    dotted_name,
)

_SCALARS = {
    "bool": "bool",
    "int": "int",
    "float": "float",
    "complex": "float",
    "Decimal": "float",
    "float64": "float",
    "float32": "float",
    "int64": "int",
    "int32": "int",
    "str": "str",
    "bytes": "bytes",
    "bytearray": "bytes",
    "memoryview": "bytes",
    "None": "none",
    "NoneType": "none",
    "datetime": "time",
    "date": "time",
    "time": "time",
    "timedelta": "time",
    "Timestamp": "time",
    "Timedelta": "time",
    "tzinfo": "time",
    "ZoneInfo": "time",
    "Any": "any",
    "object": "any",
    "Path": "str",
    "PurePath": "str",
    "PurePosixPath": "str",
    "UUID": "str",
}
_LIST_NAMES = frozenset(
    {
        "list",
        "List",
        "Sequence",
        "MutableSequence",
        "Iterable",
        "Iterator",
        "Collection",
        "Generator",
        "AsyncIterator",
        "AsyncIterable",
        "AsyncGenerator",
        "deque",
        "Deque",
        "tuple",
        "Tuple",
        "set",
        "Set",
        "frozenset",
        "FrozenSet",
        "AbstractSet",
        "MutableSet",
        "KeysView",
        "ValuesView",
        "NDArray",
        "ndarray",
    }
)
_MAP_NAMES = frozenset(
    {
        "dict",
        "Dict",
        "Mapping",
        "MutableMapping",
        "FrozenDict",
        "defaultdict",
        "DefaultDict",
        "OrderedDict",
        "Counter",
        "ChainMap",
    }
)
_TRANSPARENT = frozenset(
    {
        "Annotated",
        "Final",
        "ClassVar",
        "Required",
        "NotRequired",
        "ReadOnly",
        "Awaitable",
        "InitVar",
    }
)
_ENUM_BASES = frozenset({"Enum", "StrEnum", "IntEnum", "Flag", "IntFlag"})
_STRUCT_BASES = frozenset(
    {"BaseModel", "NamedTuple", "TypedDict", "Struct", "BaseSettings", "RootModel"}
)
_STRUCT_DECORATORS = frozenset(
    {"dataclass", "attrs", "define", "frozen", "s", "dataclass_json"}
)
_IFACE_BASES = frozenset({"Protocol", "ABC"})
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
        self._categories: dict[SymbolRef, str] = {}
        self.field_cache: dict[SymbolRef, list[tuple[str, PinType, str | None]]] = {}
        self._computing: set[SymbolRef] = set()

    def resolver(self, module: ParsedModule) -> "TypeResolver":
        return TypeResolver(self, module)

    def class_category(self, ref: SymbolRef) -> str:
        if ref in self._categories:
            return self._categories[ref]
        if ref in self._computing:
            return "object"
        self._computing.add(ref)
        try:
            category = self._compute_category(ref)
        finally:
            self._computing.discard(ref)
        self._categories[ref] = category
        return category

    def stereotype(self, ref: SymbolRef) -> str | None:
        parsed = self.workspace.parsed_class(ref)
        if parsed is None:
            return None
        category = self.class_category(ref)
        if category == "enum":
            return "enum"
        if category == "iface":
            return "protocol"
        if category == "struct":
            labels = {
                label.split("[")[0].rsplit(".", 1)[-1]
                for label, _ in self.workspace.base_classes(ref)
            }
            if labels & {"BaseModel", "BaseSettings", "RootModel"}:
                return "model"
            if "NamedTuple" in labels:
                return "namedtuple"
            if "TypedDict" in labels:
                return "typeddict"
            return "dataclass"
        for ancestor in self.workspace.class_ancestry(ref):
            for label, _ in self.workspace.base_classes(ancestor):
                last = label.split("[")[0].rsplit(".", 1)[-1]
                if last in ("Exception", "BaseException", "Warning") or last.endswith(
                    "Error"
                ):
                    return "exception"
        if ref.sym.endswith("Mixin"):
            return "mixin"
        return None

    def class_type(self, ref: SymbolRef) -> PinType:
        category = self.class_category(ref)
        return PinType(
            ref.sym.rsplit(".", 1)[-1],
            "object" if category == "iface" else category,
            ref=ref,
        )

    def _compute_category(self, ref: SymbolRef) -> str:
        parsed = self.workspace.parsed_class(ref)
        if parsed is None:
            return "object"
        for decorator in parsed.node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            name = dotted_name(target)
            if name and name.rsplit(".", 1)[-1] in _STRUCT_DECORATORS:
                return "struct"
        for label, base in self.workspace.base_classes(ref):
            last = label.split("[")[0].rsplit(".", 1)[-1]
            if last in _ENUM_BASES:
                return "enum"
            if last in _STRUCT_BASES:
                return "struct"
            if last in _IFACE_BASES:
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

    def annotation(self, node: ast.expr | None) -> PinType:
        try:
            return self._annotation(node)
        except RecursionError:
            return UNKNOWN

    def named(self, dotted: str) -> PinType:
        last = dotted.rsplit(".", 1)[-1]
        resolved = self.system.workspace.resolve(self.module, dotted)
        if (
            isinstance(resolved, SymbolRef)
            and self.system.workspace.parsed_class(resolved) is not None
        ):
            return self.system.class_type(resolved)
        if last in _SCALARS:
            return PinType(last, _SCALARS[last])
        if last in _LIST_NAMES:
            return PinType(last, "list")
        if last in _MAP_NAMES:
            return PinType(last, "map")
        if last in ("Callable", "Coroutine"):
            return PinType(last, "callable")
        if last in ("type", "Type"):
            return PinType(last, "class")
        if isinstance(resolved, ExternalRef) and last in _ENUM_BASES:
            return PinType(last, "enum")
        return PinType(last, "object")

    def _annotation(self, node: ast.expr | None) -> PinType:
        if node is None:
            return UNKNOWN
        if isinstance(node, ast.Constant):
            if node.value is None:
                return PinType("None", "none")
            if isinstance(node.value, str):
                try:
                    parsed = ast.parse(node.value, mode="eval")
                except SyntaxError:
                    return PinType(node.value, "object")
                return self._annotation(parsed.body)
            return UNKNOWN
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return self._union(_flatten_union(node))
        if isinstance(node, (ast.Name, ast.Attribute)):
            dotted = dotted_name(node)
            return self.named(dotted) if dotted else UNKNOWN
        if isinstance(node, ast.Subscript):
            return self._subscripted(node)
        return PinType(clean_label(ast.unparse(node)), "any")

    def _subscripted(self, node: ast.Subscript) -> PinType:
        base = dotted_name(node.value) or ""
        last = base.rsplit(".", 1)[-1]
        args = (
            list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
        )
        label = clean_label(ast.unparse(node))
        if last == "Optional":
            inner = self._annotation(args[0])
            return replace(inner, opt=True, label=f"Optional[{inner.label}]")
        if last == "Union":
            return self._union(args)
        if last in _TRANSPARENT:
            return self._annotation(args[0])
        if last == "Coroutine":
            return self._annotation(args[-1])
        if last == "Literal":
            values = [arg.value for arg in args if isinstance(arg, ast.Constant)]
            first = literal_type(values[0]) if values else UNKNOWN
            return PinType(label, first.cat)
        if last in ("TypeGuard", "TypeIs"):
            return PinType("bool", "bool")
        if last in ("type", "Type"):
            return replace(self._annotation(args[0]), cat="class", label=label)
        if last in ("Callable", "Awaitable"):
            return PinType(label, "callable")
        if last in _LIST_NAMES:
            return PinType(label, "list", items=self._held(args[0]))
        if last in _MAP_NAMES:
            return PinType(
                label, "map", items=self._held(args[-1]) if len(args) > 1 else None
            )
        named = self.named(base) if base else UNKNOWN
        return replace(named, label=label)

    def _held(self, node: ast.expr) -> SymbolRef | None:
        held = self._annotation(node)
        return held.ref or held.items

    def _union(self, members: list[ast.expr]) -> PinType:
        types = [self._annotation(member) for member in members]
        rest = [member for member in types if member.cat != "none"]
        has_none = len(rest) < len(types)
        if not rest:
            return PinType("None", "none")
        if len(rest) == 1:
            only = rest[0]
            return replace(
                only,
                opt=has_none or only.opt,
                label=f"Optional[{only.label}]" if has_none else only.label,
            )
        categories = {member.cat for member in rest}
        label = " | ".join(member.label for member in rest)
        return PinType(
            f"Optional[{label}]" if has_none else label,
            categories.pop() if len(categories) == 1 else "any",
            opt=has_none,
        )


def _flatten_union(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _flatten_union(node.left) + _flatten_union(node.right)
    return [node]
