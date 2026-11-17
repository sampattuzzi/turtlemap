import ast
import builtins
import copy
import json
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from code_blueprints.analysis.types import (
    UNKNOWN,
    PinType,
    TypeResolver,
    TypeSystem,
    literal_type,
)
from code_blueprints.analysis.workspace import (
    ExternalRef,
    ModuleRef,
    ParsedFunction,
    ParsedModule,
    SymbolRef,
    dotted_name,
)

MAX_NODES = 250

_TITLE_LIMIT = 60
_LITERAL_LIMIT = 40
_LABEL_LIMIT = 40
_NOTE_LIMIT = 160
_EXPRESSION_WIDTH = 44
_INPUT_NAME_LIMIT = 28

_BOOL = PinType("bool", "bool")
_INT = PinType("int", "int")
_FLOAT = PinType("float", "float")
_STR = PinType("str", "str")
_BYTES = PinType("bytes", "bytes")
_LIST = PinType("list", "list")
_TUPLE = PinType("tuple", "list")
_SET = PinType("set", "list")
_DICT = PinType("dict", "map")
_CALLABLE = PinType("Callable", "callable")
_CLASS = PinType("type", "class")
_NONE = PinType("None", "none")

_BUILTIN_NAMES = frozenset(dir(builtins))
_PURE_BUILTINS = frozenset(
    {
        "len",
        "isinstance",
        "issubclass",
        "str",
        "int",
        "float",
        "bool",
        "min",
        "max",
        "sorted",
        "abs",
        "round",
        "tuple",
        "list",
        "dict",
        "set",
        "frozenset",
        "repr",
        "hash",
        "type",
        "getattr",
        "hasattr",
        "range",
        "enumerate",
        "zip",
        "reversed",
        "any",
        "all",
        "sum",
        "map",
        "filter",
        "callable",
        "chr",
        "ord",
        "hex",
        "bin",
        "oct",
        "divmod",
        "pow",
        "format",
        "bytes",
        "slice",
        "iter",
        "id",
        "object",
        "complex",
        "ascii",
        "vars",
        "dir",
    }
)
_PURE_METHODS = frozenset(
    {
        "get",
        "items",
        "keys",
        "values",
        "lower",
        "upper",
        "startswith",
        "endswith",
        "split",
        "rsplit",
        "join",
        "format",
        "copy",
        "strip",
        "lstrip",
        "rstrip",
        "replace",
        "encode",
        "decode",
        "count",
        "index",
        "find",
        "rfind",
        "splitlines",
        "partition",
        "rpartition",
        "isdigit",
        "isalpha",
        "isalnum",
        "isnumeric",
        "isspace",
        "islower",
        "isupper",
        "casefold",
        "title",
        "capitalize",
        "zfill",
        "ljust",
        "rjust",
        "center",
        "removeprefix",
        "removesuffix",
        "total_seconds",
        "isoformat",
        "timestamp",
        "union",
        "intersection",
        "difference",
        "issubset",
        "issuperset",
        "symmetric_difference",
        "most_common",
        "model_dump",
        "model_copy",
        "model_dump_json",
        "to_json",
        "as_integer_ratio",
        "bit_length",
    }
)
_PURE_EXTERNALS = frozenset(
    {
        "dataclasses.replace",
        "dataclasses.asdict",
        "dataclasses.astuple",
        "dataclasses.fields",
        "dataclasses.field",
        "dataclasses.is_dataclass",
        "typing.cast",
        "copy.copy",
        "copy.deepcopy",
        "functools.partial",
        "functools.reduce",
        "os.path.join",
        "os.path.basename",
        "os.path.dirname",
        "os.path.splitext",
        "os.path.normpath",
        "json.dumps",
        "json.loads",
        "datetime.timedelta",
        "datetime.datetime",
        "datetime.date",
        "datetime.time",
        "datetime.timezone",
        "collections.namedtuple",
        "collections.defaultdict",
        "collections.deque",
        "collections.Counter",
        "collections.OrderedDict",
    }
)
_PURE_EXTERNAL_MODULES = frozenset(
    {
        "math",
        "cmath",
        "operator",
        "itertools",
        "statistics",
        "numpy",
        "re",
        "string",
        "textwrap",
        "fractions",
        "decimal",
    }
)
_STATIC_DECORATORS = frozenset({"staticmethod"})
_CLASS_DECORATORS = frozenset({"classmethod"})
_PROPERTY_DECORATORS = frozenset({"property", "cached_property"})
_SEQUENCE_ANNOTATIONS = frozenset(
    {
        "list",
        "List",
        "Sequence",
        "MutableSequence",
        "Iterable",
        "Iterator",
        "Collection",
        "set",
        "Set",
        "frozenset",
        "FrozenSet",
        "AbstractSet",
        "deque",
        "Deque",
        "Generator",
        "AsyncIterator",
        "AsyncIterable",
        "AsyncGenerator",
        "KeysView",
        "ValuesView",
    }
)
_MAPPING_ANNOTATIONS = frozenset(
    {
        "dict",
        "Dict",
        "Mapping",
        "MutableMapping",
        "FrozenDict",
        "defaultdict",
        "DefaultDict",
        "OrderedDict",
    }
)

_BUILTIN_PARAMETERS: dict[str, tuple[str, ...]] = {
    "len": ("obj",),
    "isinstance": ("obj", "type"),
    "issubclass": ("cls", "type"),
    "getattr": ("obj", "name", "default"),
    "hasattr": ("obj", "name"),
    "setattr": ("obj", "name", "value"),
    "str": ("value",),
    "int": ("value",),
    "float": ("value",),
    "bool": ("value",),
    "repr": ("value",),
    "abs": ("value",),
    "round": ("number", "ndigits"),
    "next": ("iterator", "default"),
}
_BUILTIN_RESULTS: dict[str, PinType] = {
    "len": _INT,
    "int": _INT,
    "round": _INT,
    "hash": _INT,
    "id": _INT,
    "ord": _INT,
    "float": _FLOAT,
    "str": _STR,
    "repr": _STR,
    "format": _STR,
    "chr": _STR,
    "hex": _STR,
    "bin": _STR,
    "oct": _STR,
    "ascii": _STR,
    "bool": _BOOL,
    "isinstance": _BOOL,
    "issubclass": _BOOL,
    "hasattr": _BOOL,
    "callable": _BOOL,
    "any": _BOOL,
    "all": _BOOL,
    "list": _LIST,
    "sorted": _LIST,
    "tuple": _TUPLE,
    "set": _SET,
    "frozenset": _SET,
    "range": _LIST,
    "enumerate": _LIST,
    "zip": _LIST,
    "reversed": _LIST,
    "map": _LIST,
    "filter": _LIST,
    "dict": _DICT,
    "bytes": _BYTES,
    "type": _CLASS,
}
_METHOD_RESULTS: dict[str, PinType] = {
    **{
        name: _STR
        for name in (
            "lower",
            "upper",
            "strip",
            "lstrip",
            "rstrip",
            "join",
            "format",
            "casefold",
            "title",
            "capitalize",
            "zfill",
            "ljust",
            "rjust",
            "center",
            "removeprefix",
            "removesuffix",
            "isoformat",
            "decode",
            "model_dump_json",
        )
    },
    **{
        name: _BOOL
        for name in (
            "startswith",
            "endswith",
            "isdigit",
            "isalpha",
            "isalnum",
            "isnumeric",
            "isspace",
            "islower",
            "isupper",
            "issubset",
            "issuperset",
        )
    },
    **{
        name: _LIST
        for name in (
            "split",
            "rsplit",
            "splitlines",
            "items",
            "keys",
            "values",
            "partition",
            "rpartition",
            "most_common",
        )
    },
    **{name: _INT for name in ("count", "index", "find", "rfind", "bit_length")},
    "encode": _BYTES,
    "total_seconds": _FLOAT,
    "timestamp": _FLOAT,
    "model_dump": _DICT,
}
_SAME_TYPE_METHODS = frozenset(
    {
        "copy",
        "replace",
        "model_copy",
        "union",
        "intersection",
        "difference",
        "symmetric_difference",
    }
)

_OPERATORS: dict[type[ast.operator], str] = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.Mod: "%",
    ast.Pow: "**",
    ast.MatMult: "@",
    ast.LShift: "<<",
    ast.RShift: ">>",
    ast.BitOr: "|",
    ast.BitAnd: "&",
    ast.BitXor: "^",
}
_COMPARISONS: dict[type[ast.cmpop], str] = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "≤",
    ast.Gt: ">",
    ast.GtE: "≥",
    ast.Is: "is",
    ast.IsNot: "is not",
    ast.In: "in",
    ast.NotIn: "not in",
}
_UNARY: dict[type[ast.unaryop], str] = {
    ast.Not: "NOT",
    ast.USub: "-",
    ast.UAdd: "+",
    ast.Invert: "~",
}
_PYTHON_OPERATORS: dict[type[ast.AST], tuple[str, int]] = {
    ast.Or: ("or", 1),
    ast.And: ("and", 2),
    ast.BitOr: ("|", 5),
    ast.BitXor: ("^", 6),
    ast.BitAnd: ("&", 7),
    ast.LShift: ("<<", 8),
    ast.RShift: (">>", 8),
    ast.Add: ("+", 9),
    ast.Sub: ("-", 9),
    ast.Mult: ("*", 10),
    ast.Div: ("/", 10),
    ast.FloorDiv: ("//", 10),
    ast.Mod: ("%", 10),
    ast.MatMult: ("@", 10),
    ast.Pow: ("**", 12),
}
_PYTHON_COMPARISONS: dict[type[ast.cmpop], str] = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Is: "is",
    ast.IsNot: "is not",
    ast.In: "in",
    ast.NotIn: "not in",
}
_COMPARE_PRECEDENCE = 4
_COMPUTATIONS = (
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.Subscript,
)
_OPERATIONS = (ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare)
_NUMERIC_MODULES = frozenset({"math", "numpy", "cmath", "statistics"})
_COMPREHENSIONS: dict[type[ast.expr], tuple[str, PinType]] = {
    ast.ListComp: ("List comprehension", _LIST),
    ast.SetComp: ("Set comprehension", _SET),
    ast.DictComp: ("Dict comprehension", _DICT),
    ast.GeneratorExp: ("Generator", _LIST),
}


def build_function_graph(
    types: TypeSystem, module: ParsedModule, function: ParsedFunction
) -> dict[str, Any]:
    return _FunctionGraphBuilder(types, module, function).build()


@dataclass(frozen=True)
class _Value:
    type: PinType = field(compare=False)
    node: str | None = None
    pin: str | None = None
    literal: str | None = None
    annotation: tuple[ast.expr, ParsedModule] | None = field(
        default=None, compare=False
    )


@dataclass(frozen=True)
class _Folded:
    inputs: list[tuple[str, _Value]]
    result: PinType
    lines: list[str]


@dataclass(frozen=True, eq=False)
class _PendingSelect:
    condition: _Value
    when_true: "_Binding"
    when_false: "_Binding"
    line: int


_Binding = _Value | _PendingSelect
_Environment = dict[str, _Binding]


@dataclass
class _Pin:
    name: str
    type: PinType
    literal: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "type": self.type.to_json()}
        if self.literal is not None:
            out["lit"] = self.literal
        return out


@dataclass
class _Node:
    id: str
    kind: str
    title: str
    line: int
    ins: list[_Pin] = field(default_factory=list)
    outs: list[_Pin] = field(default_factory=list)
    target: SymbolRef | None = None
    external: str | None = None
    notes: list[str] = field(default_factory=list)
    code: str | None = None
    exec_in: bool = False
    exec_out: bool = False
    exec_outs: list[str] | None = None
    expression: list[str] | None = None

    def output(self, name: str) -> _Pin | None:
        return next((pin for pin in self.outs if pin.name == name), None)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "line": self.line,
            "ins": [pin.to_json() for pin in self.ins],
            "outs": [pin.to_json() for pin in self.outs],
        }
        if self.target is not None:
            out["target"] = self.target.to_json()
        if self.external is not None:
            out["external"] = self.external
        if self.notes:
            out["note"] = "; ".join(self.notes)
        if self.code:
            out["code"] = self.code
        if self.exec_in:
            out["execIn"] = True
        if self.exec_out:
            out["execOut"] = True
        if self.exec_outs is not None:
            out["execOuts"] = list(self.exec_outs)
        if self.expression is not None:
            out["expr"] = list(self.expression)
        return out


class _GraphFull(Exception):
    pass


class _Graph:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.nodes: list[_Node] = []
        self.edges: list[dict[str, str]] = []
        self.exec: list[dict[str, str]] = []

    def add(
        self,
        kind: str,
        title: str,
        line: int,
        *,
        target: SymbolRef | None = None,
        external: str | None = None,
        note: str | None = None,
        code: str | None = None,
        exec_outs: Sequence[str] | None = None,
    ) -> _Node:
        if len(self.nodes) >= self.limit:
            raise _GraphFull()
        return self.add_unbounded(
            kind,
            title,
            line,
            target=target,
            external=external,
            note=note,
            code=code,
            exec_outs=exec_outs,
        )

    def add_unbounded(
        self,
        kind: str,
        title: str,
        line: int,
        *,
        target: SymbolRef | None = None,
        external: str | None = None,
        note: str | None = None,
        code: str | None = None,
        exec_outs: Sequence[str] | None = None,
    ) -> _Node:
        node = _Node(
            f"n{len(self.nodes)}",
            kind,
            _shorten(title, _TITLE_LIMIT),
            line,
            target=target,
            external=external,
            exec_outs=_unique_labels(exec_outs) if exec_outs is not None else None,
        )
        if note:
            node.notes.append(_shorten(note, _NOTE_LIMIT))
        if code:
            node.code = _shorten(code, _NOTE_LIMIT)
        self.nodes.append(node)
        return node

    def connect(
        self, node: _Node, name: str, value: _Value, pin_type: PinType | None = None
    ) -> None:
        unique = _unique(name, {pin.name for pin in node.ins})
        node.ins.append(
            _Pin(
                unique,
                pin_type or value.type,
                value.literal if value.node is None else None,
            )
        )
        if value.node is not None and value.pin is not None:
            self.edges.append(
                {"from": value.node, "fp": value.pin, "to": node.id, "tp": unique}
            )

    def output(
        self,
        node: _Node,
        name: str,
        pin_type: PinType,
        annotation: tuple[ast.expr, ParsedModule] | None = None,
    ) -> _Value:
        unique = _unique(name, {pin.name for pin in node.outs})
        node.outs.append(_Pin(unique, pin_type))
        return _Value(pin_type, node.id, unique, annotation=annotation)

    def link(self, source: _Node, label: str, target: _Node) -> None:
        if label == "then":
            source.exec_out = True
        elif source.exec_outs is None or label not in source.exec_outs:
            source.exec_outs = [*(source.exec_outs or []), label]
        target.exec_in = True
        self.exec.append({"from": source.id, "fp": label, "to": target.id})

    def strip_exec_when_only_returns(self) -> None:
        if any(
            node.kind not in ("entry", "return") and (node.exec_in or node.exec_out)
            for node in self.nodes
        ):
            return
        self.exec.clear()
        for node in self.nodes:
            node.exec_in = False
            node.exec_out = False

    def to_json(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_json() for node in self.nodes],
            "edges": list(self.edges),
            "exec": list(self.exec),
        }


@dataclass
class _Callee:
    kind: str
    title: str
    pure: bool
    result: PinType = UNKNOWN
    target: SymbolRef | None = None
    external: str | None = None
    receiver: _Value | None = None
    receiver_name: str = "self"
    parameters: tuple[str, ...] = ()
    vararg: str | None = None
    parameter_types: dict[str, PinType] = field(default_factory=dict)
    note: str | None = None


@dataclass(frozen=True)
class _Outcome:
    value: _Value | None
    terminated: bool


@dataclass(frozen=True)
class _Member:
    annotation: ast.expr | None
    module: ParsedModule
    is_method: bool = False


@dataclass(frozen=True)
class _Argument:
    name: str
    value: _Value
    pin_type: PinType


_Tail = tuple[_Node, str]


class _FunctionGraphBuilder:
    def __init__(
        self, types: TypeSystem, module: ParsedModule, function: ParsedFunction
    ) -> None:
        self._types = types
        self._workspace = types.workspace
        self._module = module
        self._function = function
        self._graph = _Graph(MAX_NODES)
        self._resolvers: dict[str, TypeResolver] = {}
        self._env: _Environment = {}
        self._materialized: dict[_PendingSelect, _Value] = {}
        self._tails: list[_Tail] = []
        self._breaks: dict[tuple[str | None, str | None, str | None], _Node] = {}
        self._globals: dict[str, _Value] = {}
        self._carried: frozenset[str] = frozenset()
        self._loop_exits: list[list[_Tail]] = []
        self._declared_globals: set[str] = set()
        self._local_functions: set[str] = set()
        self._local_names = _local_names(function.node)
        self._parameter_annotations = {
            argument.arg: argument.annotation
            for argument in _all_arguments(function.node.args)
            if argument.annotation is not None
        }
        self._attribute_counts = _attribute_counts(function.node)
        self._module_variables = _module_variables(module)
        self._members: dict[SymbolRef, dict[str, _Member]] = {}
        self._return_type = (
            self._resolver(module).annotation(function.node.returns)
            if function.node.returns is not None
            else None
        )
        self._truncated = False

    def build(self) -> dict[str, Any]:
        entry = self._entry()
        self._tails = [(entry, "then")]
        try:
            self._run_block(self._function.node.body, function_level=True)
        except _GraphFull:
            self._mark_truncated()
        self._graph.strip_exec_when_only_returns()
        graph = self._graph.to_json()
        if self._truncated:
            graph["truncated"] = True
        return graph

    def _entry(self) -> _Node:
        node = self._graph.add(
            "entry", self._function.node.name, self._function.node.lineno
        )
        arguments = self._function.node.args
        positional = [*arguments.posonlyargs, *arguments.args]
        for index, argument in enumerate(positional):
            self._bind_parameter(
                node, argument.arg, argument.arg, self._parameter_type(argument, index)
            )
        if arguments.vararg is not None:
            inner = self._annotation_type(arguments.vararg.annotation)
            self._bind_parameter(
                node,
                arguments.vararg.arg,
                f"*{arguments.vararg.arg}",
                PinType(f"tuple[{inner.label}, ...]", "list"),
            )
        for argument in arguments.kwonlyargs:
            self._bind_parameter(
                node, argument.arg, argument.arg, self._parameter_type(argument, -1)
            )
        if arguments.kwarg is not None:
            inner = self._annotation_type(arguments.kwarg.annotation)
            self._bind_parameter(
                node,
                arguments.kwarg.arg,
                f"**{arguments.kwarg.arg}",
                PinType(f"dict[str, {inner.label}]", "map"),
            )
        return node

    def _bind_parameter(
        self, node: _Node, name: str, pin: str, pin_type: PinType
    ) -> None:
        annotation = self._parameter_annotations.get(name)
        self._env[name] = self._graph.output(
            node,
            pin,
            pin_type,
            (annotation, self._module) if annotation is not None else None,
        )

    def _parameter_type(self, argument: ast.arg, index: int) -> PinType:
        owner = self._owner_ref()
        if index == 0 and owner is not None and argument.annotation is None:
            decorators = _decorator_names(self._function.node)
            if decorators & _STATIC_DECORATORS:
                return UNKNOWN
            owner_type = self._types.class_type(owner)
            if decorators & _CLASS_DECORATORS:
                return replace(
                    owner_type, cat="class", label=f"type[{owner_type.label}]"
                )
            return owner_type
        return self._annotation_type(argument.annotation)

    def _owner_ref(self) -> SymbolRef | None:
        qualname = self._function.class_qualname
        return SymbolRef(self._module.path, qualname) if qualname is not None else None

    def _mark_truncated(self) -> None:
        self._truncated = True
        last_line = (
            self._graph.nodes[-1].line
            if self._graph.nodes
            else self._function.node.lineno
        )
        marker = self._graph.add_unbounded(
            "return",
            "Truncated",
            last_line,
            note=f"Graph stopped after {MAX_NODES} nodes",
        )
        if any(node.exec_in or node.exec_out for node in self._graph.nodes):
            self._step(marker)

    def _run_block(
        self, statements: Sequence[ast.stmt], *, function_level: bool
    ) -> None:
        for index, statement in enumerate(statements):
            rest = statements[index:]
            if isinstance(statement, ast.If) and self._starts_return_region(
                rest, function_level=function_level
            ):
                self._return_region(rest)
                return
            self._statement(statement)

    def _statement(self, statement: ast.stmt) -> None:
        try:
            self._dispatch_statement(statement)
        except _GraphFull:
            raise
        except Exception as error:
            node = self._graph.add(
                "ext",
                _source_title(statement),
                statement.lineno,
                note=f"Not drawn: {type(error).__name__}",
            )
            self._step(node)

    def _dispatch_statement(self, statement: ast.stmt) -> None:
        if isinstance(statement, ast.Expr):
            self._expression_statement(statement.value)
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            self._assign(statement, exec_candidate=True)
        elif isinstance(statement, ast.AugAssign):
            self._augmented_assign(statement)
        elif isinstance(statement, ast.Return):
            value = (
                self._expr(statement.value, exec_candidate=True)
                if statement.value is not None
                else None
            )
            self._emit_return(value, statement.lineno)
        elif isinstance(statement, ast.If):
            self._if(statement)
        elif isinstance(statement, (ast.For, ast.AsyncFor)):
            self._for(statement)
        elif isinstance(statement, ast.While):
            self._while(statement)
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            self._with(statement)
        elif isinstance(statement, (ast.Try, ast.TryStar)):
            self._try(statement)
        elif isinstance(statement, ast.Raise):
            self._raise(statement)
        elif isinstance(statement, ast.Match):
            self._match(statement)
        elif isinstance(statement, ast.Assert):
            self._assert(statement)
        elif isinstance(statement, ast.Delete):
            self._delete(statement)
        elif isinstance(statement, ast.Break):
            if self._loop_exits:
                self._loop_exits[-1].extend(self._tails)
            self._tails = []
        elif isinstance(statement, ast.Continue):
            self._tails = []
        elif isinstance(statement, (ast.Global, ast.Nonlocal)):
            self._declared_globals.update(statement.names)
        elif isinstance(
            statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            self._local_functions.add(statement.name)
            self._env.pop(statement.name, None)
        elif (
            isinstance(statement, (ast.Pass, ast.Import, ast.ImportFrom))
            or type(statement).__name__ == "TypeAlias"
        ):
            return
        else:
            self._step(
                self._graph.add("ext", _source_title(statement), statement.lineno)
            )

    def _step(self, node: _Node) -> None:
        for source, label in self._tails:
            self._graph.link(source, label, node)
        self._tails = [(node, "then")]

    def _expression_statement(self, value: ast.expr) -> None:
        if isinstance(value, ast.Constant):
            return
        if isinstance(value, ast.Call):
            self._call(value, exec_candidate=True, out_names=())
        elif isinstance(value, ast.Await) and isinstance(value.value, ast.Call):
            self._call(value.value, exec_candidate=True, out_names=(), awaited=True)
        elif isinstance(value, (ast.Yield, ast.YieldFrom)):
            self._yield(value, discard=True)
        else:
            self._expr(value)

    def _assign(
        self, statement: ast.Assign | ast.AnnAssign, *, exec_candidate: bool
    ) -> None:
        if statement.value is None:
            return
        targets = (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
        )
        names = _assigned_names(targets[0]) if len(targets) == 1 else None
        call, awaited = _unwrap_call(statement.value)
        if (
            call is not None
            and names is not None
            and len(names) > 1
            and isinstance(targets[0], (ast.Tuple, ast.List))
        ):
            outputs = self._call(
                call, exec_candidate=exec_candidate, out_names=names, awaited=awaited
            )
            for target, output in zip(_flat_targets(targets[0]), outputs):
                self._bind(target, output, statement.lineno)
            return
        out_name = names[0] if names is not None and len(names) == 1 else ""
        value = self._expr(
            statement.value, exec_candidate=exec_candidate, out_name=out_name
        )
        if isinstance(statement, ast.AnnAssign):
            value = replace(
                value,
                type=self._annotation_type(statement.annotation),
                annotation=(statement.annotation, self._module),
            )
        for target in targets:
            self._bind(target, value, statement.lineno)

    def _bind(self, target: ast.expr, value: _Value, line: int) -> None:
        if isinstance(target, ast.Name):
            self._bind_name(target.id, value, line)
        elif isinstance(target, ast.Starred):
            self._bind(target.value, value, line)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element, part in zip(target.elts, self._unpack(value, target, line)):
                self._bind(element, part, line)
        elif isinstance(target, ast.Attribute):
            node = self._graph.add("set", f"Set {ast.unparse(target)}", line)
            self._graph.connect(node, _pin_name(target.value), self._expr(target.value))
            self._graph.connect(node, "value", value)
            self._step(node)
        elif isinstance(target, ast.Subscript):
            container = self._expr(target.value)
            key = self._expr(target.slice)
            node = self._graph.add("set", f"Set {ast.unparse(target)}", line)
            self._graph.connect(node, _pin_name(target.value), container)
            self._graph.connect(node, "key", key)
            self._graph.connect(node, "value", value)
            self._step(node)

    def _bind_name(self, name: str, value: _Value, line: int) -> None:
        if name in self._carried or name in self._declared_globals:
            node = self._graph.add("set", f"Set {name}", line)
            self._graph.connect(node, "value", value)
            self._step(node)
            value = self._graph.output(node, name, value.type, value.annotation)
        self._env[name] = value

    def _unpack(
        self, value: _Value, target: ast.Tuple | ast.List, line: int
    ) -> list[_Value]:
        node = self._graph.add("op", "Unpack", line)
        self._graph.connect(node, "value", value)
        return [
            self._graph.output(node, _target_label(element), UNKNOWN)
            for element in target.elts
        ]

    def _augmented_assign(self, statement: ast.AugAssign) -> None:
        symbol = _OPERATORS.get(type(statement.op), "?")
        target = statement.target
        value = self._expr(statement.value)
        if isinstance(target, ast.Name):
            current = self._name_value(target.id, statement.lineno)
            node = self._graph.add(
                "set", f"Set {target.id} {symbol}=", statement.lineno
            )
            self._graph.connect(node, target.id, current)
            self._graph.connect(node, "value", value)
            self._step(node)
            self._env[target.id] = self._graph.output(
                node, target.id, current.type, current.annotation
            )
            return
        base = (
            target.value
            if isinstance(target, (ast.Attribute, ast.Subscript))
            else target
        )
        container = self._expr(base)
        key = self._expr(target.slice) if isinstance(target, ast.Subscript) else None
        node = self._graph.add(
            "set", f"Set {ast.unparse(target)} {symbol}=", statement.lineno
        )
        self._graph.connect(node, _pin_name(base), container)
        if key is not None:
            self._graph.connect(node, "key", key)
        self._graph.connect(node, "value", value)
        self._step(node)

    def _emit_return(self, value: _Value | None, line: int) -> None:
        node = self._graph.add("return", "Return", line)
        if value is not None:
            declared = self._return_type
            name = declared.label if declared is not None else "value"
            self._graph.connect(
                node,
                name,
                value,
                (
                    declared
                    if declared is not None and declared.cat != "any"
                    else value.type
                ),
            )
        self._step(node)
        self._tails = []

    def _if(self, statement: ast.If) -> None:
        if self._is_data_block([statement]) and not _contains_return([statement]):
            self._merge_if(statement)
        else:
            self._branch_if(statement)

    def _merge_if(self, statement: ast.If) -> None:
        condition = self._expr(statement.test)
        saved = dict(self._env)
        self._data_block(statement.body)
        true_env = self._env
        self._env = dict(saved)
        self._data_block(statement.orelse)
        self._env = self._merge(condition, true_env, self._env, statement.lineno)

    def _branch_if(self, statement: ast.If) -> None:
        condition: _Value | None = None
        if self._folds(statement.test, named=True):
            node = self._inline_condition(
                statement.test,
                lambda: self._graph.add(
                    "branch", "Branch", statement.lineno, exec_outs=["True", "False"]
                ),
            )
        else:
            condition = self._expr(statement.test, exec_candidate=True)
            node = self._graph.add(
                "branch", "Branch", statement.lineno, exec_outs=["True", "False"]
            )
            self._graph.connect(node, "condition", condition, _BOOL)
        self._step(node)
        saved = dict(self._env)
        self._tails = [(node, "True")]
        self._run_block(statement.body, function_level=False)
        true_tails, true_env = self._tails, self._env
        self._env = dict(saved)
        self._tails = [(node, "False")]
        self._run_block(statement.orelse, function_level=False)
        false_tails, false_env = self._tails, self._env
        self._tails = true_tails + false_tails
        if not true_tails and false_tails:
            self._env = false_env
        elif true_tails and not false_tails:
            self._env = true_env
        else:
            if condition is None:
                condition = (
                    self._graph.output(node, "condition", _BOOL)
                    if _differ(true_env, false_env)
                    else _Value(_BOOL)
                )
            self._env = self._merge(condition, true_env, false_env, statement.lineno)

    def _merge(
        self,
        condition: _Value,
        true_env: _Environment,
        false_env: _Environment,
        line: int,
    ) -> _Environment:
        merged: _Environment = {}
        for name in [*true_env, *(name for name in false_env if name not in true_env)]:
            when_true, when_false = true_env.get(name), false_env.get(name)
            if when_true is None or when_false is None or when_true == when_false:
                present = when_true if when_true is not None else when_false
                if present is not None:
                    merged[name] = present
                continue
            merged[name] = _PendingSelect(condition, when_true, when_false, line)
        return merged

    def _materialize(self, binding: _Binding) -> _Value:
        if isinstance(binding, _Value):
            return binding
        cached = self._materialized.get(binding)
        if cached is None:
            when_true = self._materialize(binding.when_true)
            when_false = self._materialize(binding.when_false)
            cached = self._select(
                binding.condition, when_true, when_false, binding.line
            )
            self._materialized[binding] = cached
        return cached

    def _select(
        self, condition: _Value, when_true: _Value, when_false: _Value, line: int
    ) -> _Value:
        if when_true == when_false:
            return when_true
        result = _select_type(when_true, when_false)
        node = self._graph.add("select", "Select", line)
        self._graph.connect(node, "condition", condition, _BOOL)
        self._graph.connect(node, "if true", when_true)
        self._graph.connect(node, "if false", when_false)
        return self._graph.output(node, "", result)

    def _select_on(
        self,
        condition: _Value | _Folded,
        when_true: _Value,
        when_false: _Value,
        line: int,
    ) -> _Value:
        if isinstance(condition, _Value):
            return self._select(condition, when_true, when_false, line)
        if when_true == when_false:
            return when_true
        node = self._graph.add("select", "Select", line)
        self._write_expression(node, condition)
        self._graph.connect(node, "if true", when_true)
        self._graph.connect(node, "if false", when_false)
        return self._graph.output(node, "", _select_type(when_true, when_false))

    def _starts_return_region(
        self, statements: Sequence[ast.stmt], *, function_level: bool
    ) -> bool:
        if not _contains_return(statements[:1]) or not self._is_data_block(statements):
            return False
        return function_level or _always_terminates(statements)

    def _return_region(self, statements: Sequence[ast.stmt]) -> None:
        outcome = self._data_block(statements)
        value = (
            outcome.value
            if outcome.terminated and outcome.value is not None
            else _none_literal()
        )
        self._emit_return(value, statements[-1].lineno)

    def _data_block(self, statements: Sequence[ast.stmt]) -> _Outcome:
        for index, statement in enumerate(statements):
            if isinstance(statement, ast.Return):
                value = (
                    self._expr(statement.value)
                    if statement.value is not None
                    else _none_literal()
                )
                return _Outcome(value, True)
            if isinstance(statement, ast.If):
                outcome = self._data_if(statement, statements[index + 1 :])
                if outcome is not None:
                    return outcome
            elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                self._assign(statement, exec_candidate=False)
        return _Outcome(None, False)

    def _data_if(self, statement: ast.If, rest: Sequence[ast.stmt]) -> _Outcome | None:
        condition: _Value | _Folded = (
            self._fold(statement.test)
            if self._folds(statement.test, named=True)
            else self._expr(statement.test)
        )
        saved = dict(self._env)
        when_true = self._data_block(statement.body)
        true_env = self._env
        self._env = dict(saved)
        when_false = self._data_block(statement.orelse)
        if when_true.terminated and when_false.terminated:
            return _Outcome(
                self._select_on(
                    condition,
                    _returned(when_true),
                    _returned(when_false),
                    statement.lineno,
                ),
                True,
            )
        if not when_true.terminated and not when_false.terminated:
            if isinstance(condition, _Folded):
                condition = self._expression_node(condition, "Check", statement.lineno)
            self._env = self._merge(condition, true_env, self._env, statement.lineno)
            return None
        if when_false.terminated:
            self._env = true_env
        continuation = self._data_block(rest)
        later = _returned(continuation)
        if when_true.terminated:
            return _Outcome(
                self._select_on(
                    condition, _returned(when_true), later, statement.lineno
                ),
                True,
            )
        return _Outcome(
            self._select_on(condition, later, _returned(when_false), statement.lineno),
            True,
        )

    def _is_data_block(self, statements: Sequence[ast.stmt]) -> bool:
        return all(self._is_data_statement(statement) for statement in statements)

    def _is_data_statement(self, statement: ast.stmt) -> bool:
        if isinstance(statement, ast.Pass) or (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
        ):
            return True
        if isinstance(statement, ast.Return):
            return statement.value is None or not _suspends(statement.value)
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            names = [
                name
                for target in targets
                for name in (_assigned_names(target) or ["."])
            ]
            if any(
                not name.isidentifier()
                or name in self._carried
                or name in self._declared_globals
                for name in names
            ):
                return False
            value = statement.value
            return value is None or (
                not _suspends(value) and not self._is_effectful_call(value)
            )
        if isinstance(statement, ast.If):
            return (
                not _suspends(statement.test)
                and self._is_data_block(statement.body)
                and self._is_data_block(statement.orelse)
            )
        return False

    def _is_effectful_call(self, value: ast.expr) -> bool:
        return isinstance(value, ast.Call) and not self._call_is_pure(value)

    def _for(self, statement: ast.For | ast.AsyncFor) -> None:
        items = self._expr(statement.iter, exec_candidate=True)
        targets = _flat_targets(statement.target)
        title = ", ".join(_target_label(target) for target in targets)
        node = self._graph.add(
            "loop",
            f"For each {title}",
            statement.lineno,
            exec_outs=["Loop body", "Completed"],
            note="async for" if isinstance(statement, ast.AsyncFor) else None,
        )
        self._graph.connect(node, "items", items)
        element = self._element_type(items) if len(targets) == 1 else UNKNOWN
        outputs = [
            self._graph.output(node, _target_label(target), element)
            for target in targets
        ]
        self._step(node)
        for target, output in zip(targets, outputs):
            if isinstance(target, ast.Name):
                self._env[target.id] = output
            else:
                self._bind(target, output, statement.lineno)
        self._loop_body(node, statement.body, statement.orelse)

    def _while(self, statement: ast.While) -> None:
        if self._folds(statement.test, named=True):
            node = self._inline_condition(
                statement.test,
                lambda: self._graph.add(
                    "loop",
                    "While",
                    statement.lineno,
                    exec_outs=["Loop body", "Completed"],
                ),
            )
        else:
            condition = self._expr(statement.test)
            node = self._graph.add(
                "loop",
                f"While {ast.unparse(statement.test)}",
                statement.lineno,
                exec_outs=["Loop body", "Completed"],
            )
            self._graph.connect(node, "condition", condition, _BOOL)
        self._step(node)
        self._loop_body(node, statement.body, statement.orelse)

    def _loop_body(
        self, node: _Node, body: Sequence[ast.stmt], orelse: Sequence[ast.stmt]
    ) -> None:
        carried = self._carried
        self._carried = carried | frozenset(self._env)
        self._loop_exits.append([])
        self._tails = [(node, "Loop body")]
        try:
            self._run_block(body, function_level=False)
        finally:
            exits = self._loop_exits.pop()
            self._carried = carried
        self._tails = [(node, "Completed")]
        self._run_block(orelse, function_level=False)
        self._tails = self._tails + exits

    def _with(self, statement: ast.With | ast.AsyncWith) -> None:
        contexts = [self._expr(item.context_expr) for item in statement.items]
        title = ", ".join(ast.unparse(item.context_expr) for item in statement.items)
        node = self._graph.add(
            "ext",
            f"With {title}",
            statement.lineno,
            note="async with" if isinstance(statement, ast.AsyncWith) else None,
        )
        bindings: list[tuple[ast.expr, _Value]] = []
        for item, context in zip(statement.items, contexts):
            self._graph.connect(node, "context", context)
            if item.optional_vars is not None:
                entered = (
                    context.type
                    if isinstance(item.optional_vars, ast.Name)
                    else UNKNOWN
                )
                bindings.append(
                    (
                        item.optional_vars,
                        self._graph.output(
                            node, _target_label(item.optional_vars), entered
                        ),
                    )
                )
        self._step(node)
        for target, value in bindings:
            self._bind(target, value, statement.lineno)
        self._run_block(statement.body, function_level=False)

    def _try(self, statement: ast.Try | ast.TryStar) -> None:
        labels = [
            "Try",
            *(
                (
                    f"except {ast.unparse(handler.type)}"
                    if handler.type is not None
                    else "except"
                )
                for handler in statement.handlers
            ),
        ]
        node = self._graph.add(
            "branch",
            "Try",
            statement.lineno,
            exec_outs=labels,
            note="finally runs afterwards" if statement.finalbody else None,
        )
        unique_labels = node.exec_outs or labels
        self._step(node)
        saved = dict(self._env)
        self._tails = [(node, unique_labels[0])]
        self._run_block(statement.body, function_level=False)
        self._run_block(statement.orelse, function_level=False)
        tails: list[_Tail] = self._tails
        env: _Environment = self._env
        for handler, label in zip(statement.handlers, unique_labels[1:]):
            self._env = dict(saved)
            if handler.name:
                self._env[handler.name] = self._graph.output(
                    node, handler.name, self._exception_type(handler.type)
                )
            self._tails = [(node, label)]
            self._run_block(handler.body, function_level=False)
            tails = tails + self._tails
            env = {**self._env, **env}
        self._tails, self._env = tails, env
        if statement.finalbody and not tails:
            self._tails = [(node, "Finally")]
            self._run_block(statement.finalbody, function_level=False)
            self._tails = []
            return
        self._run_block(statement.finalbody, function_level=False)

    def _exception_type(self, annotation: ast.expr | None) -> PinType:
        if isinstance(annotation, (ast.Name, ast.Attribute)):
            return self._annotation_type(annotation)
        return PinType("Exception", "object")

    def _raise(self, statement: ast.Raise) -> None:
        exception = statement.exc
        if exception is None:
            node = self._graph.add("raise", "Re-raise", statement.lineno)
        elif isinstance(exception, ast.Call) and self._raises_class(exception):
            callee = self._resolve_callee(exception)
            arguments = self._arguments(exception, callee, first_fallback="message")
            name = _short_name(callee.title.removeprefix("Make "))
            node = self._graph.add(
                "raise",
                f"Raise {name}",
                statement.lineno,
                target=callee.target,
                external=callee.external,
            )
            self._connect_arguments(node, arguments)
        else:
            value = self._expr(exception)
            title = (
                f"Raise {_short_name(ast.unparse(exception))}"
                if value.literal is not None
                else "Raise"
            )
            node = self._graph.add(
                "raise",
                title,
                statement.lineno,
                target=value.type.ref if value.literal is not None else None,
            )
            if value.literal is None:
                self._graph.connect(node, "error", value)
        if statement.cause is not None:
            self._graph.connect(node, "cause", self._expr(statement.cause))
        self._step(node)
        self._tails = []

    def _raises_class(self, call: ast.Call) -> bool:
        name = dotted_name(call.func)
        if name is None or self._is_local(name.split(".")[0]):
            return False
        last = name.rsplit(".", 1)[-1]
        return last[:1].isupper()

    def _match(self, statement: ast.Match) -> None:
        subject = self._expr(statement.subject, exec_candidate=True)
        labels = [
            _shorten(
                "case "
                + ast.unparse(case.pattern)
                + (f" if {ast.unparse(case.guard)}" if case.guard else ""),
                _LABEL_LIMIT,
            )
            for case in statement.cases
        ]
        exhaustive = any(
            isinstance(case.pattern, ast.MatchAs)
            and case.pattern.pattern is None
            and case.guard is None
            for case in statement.cases
        )
        node = self._graph.add(
            "branch",
            f"Match {ast.unparse(statement.subject)}",
            statement.lineno,
            exec_outs=labels if exhaustive else [*labels, "No match"],
        )
        unique_labels = node.exec_outs or labels
        self._graph.connect(node, "subject", subject)
        self._step(node)
        saved = dict(self._env)
        tails: list[_Tail] = [] if exhaustive else [(node, unique_labels[-1])]
        env: _Environment = dict(saved)
        for case, label in zip(statement.cases, unique_labels):
            self._env = dict(saved)
            for name in _pattern_captures(case.pattern):
                self._env[name] = self._graph.output(node, name, UNKNOWN)
            if case.guard is not None:
                self._expr(case.guard)
            self._tails = [(node, label)]
            self._run_block(case.body, function_level=False)
            tails = tails + self._tails
            env.update(self._env)
        self._tails, self._env = tails, env

    def _assert(self, statement: ast.Assert) -> None:
        condition = self._expr(statement.test)
        node = self._graph.add("raise", "Assert", statement.lineno)
        self._graph.connect(node, "condition", condition, _BOOL)
        if statement.msg is not None:
            self._graph.connect(node, "message", self._expr(statement.msg))
        self._step(node)

    def _delete(self, statement: ast.Delete) -> None:
        for target in statement.targets:
            if isinstance(target, ast.Name):
                self._env.pop(target.id, None)
                continue
            base = (
                target.value
                if isinstance(target, (ast.Attribute, ast.Subscript))
                else target
            )
            container = self._expr(base)
            key = (
                self._expr(target.slice) if isinstance(target, ast.Subscript) else None
            )
            node = self._graph.add(
                "set", f"Delete {ast.unparse(target)}", statement.lineno
            )
            self._graph.connect(node, _pin_name(base), container)
            if key is not None:
                self._graph.connect(node, "key", key)
            self._step(node)

    def _yield(self, expression: ast.Yield | ast.YieldFrom, *, discard: bool) -> _Value:
        value = self._expr(expression.value) if expression.value is not None else None
        node = self._graph.add(
            "return",
            "Yield from" if isinstance(expression, ast.YieldFrom) else "Yield",
            expression.lineno,
        )
        if value is not None:
            self._graph.connect(node, "value", value)
        self._step(node)
        if discard:
            return _none_literal()
        return self._graph.output(node, "sent", UNKNOWN)

    def _expr(
        self, expression: ast.expr, *, exec_candidate: bool = False, out_name: str = ""
    ) -> _Value:
        literal = _literal(expression)
        if literal is not None:
            return literal
        if isinstance(expression, ast.Name):
            return self._name_value(expression.id, expression.lineno)
        if self._folds(expression, named=bool(out_name)):
            return self._expression(expression, out_name)
        if isinstance(expression, ast.Attribute):
            return self._attribute(expression)
        if isinstance(expression, ast.Call):
            if _is_super_call(expression) and not self._is_local("super"):
                return self._super_value()
            return self._call(
                expression, exec_candidate=exec_candidate, out_names=(out_name,)
            )[0]
        if isinstance(expression, ast.Await):
            return self._await(
                expression, exec_candidate=exec_candidate, out_name=out_name
            )
        if isinstance(expression, ast.BoolOp):
            return self._bool_op(expression)
        if isinstance(expression, ast.BinOp):
            return self._binary(expression)
        if isinstance(expression, ast.UnaryOp):
            return self._unary(expression)
        if isinstance(expression, ast.Compare):
            return self._compare(expression)
        if isinstance(expression, ast.IfExp):
            condition = self._expr(expression.test)
            return self._select(
                condition,
                self._expr(expression.body),
                self._expr(expression.orelse),
                expression.lineno,
            )
        if isinstance(expression, ast.Subscript):
            return self._subscript(expression)
        if isinstance(expression, ast.JoinedStr):
            return self._format_text(expression)
        if isinstance(expression, (ast.Tuple, ast.List, ast.Set, ast.Dict)):
            return self._collection(expression)
        if isinstance(
            expression, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        ):
            title, result = _COMPREHENSIONS[type(expression)]
            return self._opaque(expression, title, result, code=ast.unparse(expression))
        if isinstance(expression, ast.Lambda):
            return self._opaque(
                expression, "Lambda", _CALLABLE, code=ast.unparse(expression)
            )
        if isinstance(expression, ast.NamedExpr):
            value = self._expr(expression.value, out_name=expression.target.id)
            self._env[expression.target.id] = value
            return value
        if isinstance(expression, ast.Starred):
            return self._expr(expression.value)
        if isinstance(expression, (ast.Yield, ast.YieldFrom)):
            return self._yield(expression, discard=False)
        if isinstance(expression, ast.FormattedValue):
            return self._expr(expression.value)
        return self._opaque(expression, ast.unparse(expression), UNKNOWN, code=None)

    def _name_value(self, name: str, line: int) -> _Value:
        if name in self._env:
            value = self._materialize(self._env[name])
            self._env[name] = value
            return value
        if name in self._local_functions:
            return _Value(_CALLABLE, literal=name)
        if name in self._local_names and name not in self._declared_globals:
            return self._cached_variable(
                name,
                line,
                lambda: self._graph.add(
                    "var", name, line, note="Assigned later in the function"
                ),
                UNKNOWN,
            )
        return self._global_value(name, line)

    def _is_local(self, name: str) -> bool:
        return (
            name in self._env
            or name in self._local_functions
            or (name in self._local_names and name not in self._declared_globals)
        )

    def _global_value(self, dotted: str, line: int) -> _Value:
        head = dotted.split(".")[0]
        if (
            head in _BUILTIN_NAMES
            and head not in self._module.imports
            and head not in self._module.top_level
            and head not in self._module_variables
        ):
            builtin = getattr(builtins, head, None)
            return _Value(
                PinType(head, "class") if isinstance(builtin, type) else _CALLABLE,
                literal=dotted,
            )
        if head in self._module_variables and "." not in dotted:
            return self._cached_variable(
                dotted,
                line,
                lambda: self._graph.add("var", dotted, line),
                self._module_variable_type(head),
            )
        resolved = self._workspace.resolve(self._module, dotted)
        if isinstance(resolved, SymbolRef):
            return self._project_symbol_value(dotted, resolved, line)
        if isinstance(resolved, ExternalRef):
            external = _external_name(resolved)
            last = dotted.rsplit(".", 1)[-1]
            if last[:1].isupper():
                return _Value(
                    PinType(last, "class" if not last.isupper() else "any"),
                    literal=dotted,
                )
            return self._cached_variable(
                dotted,
                line,
                lambda: self._graph.add("var", dotted, line, external=external),
                UNKNOWN,
            )
        if isinstance(resolved, ModuleRef):
            return _Value(UNKNOWN, literal=dotted)
        return self._cached_variable(
            dotted, line, lambda: self._graph.add("var", dotted, line), UNKNOWN
        )

    def _module_variable_type(self, name: str) -> PinType:
        annotation, value = self._module_variables[name]
        return (
            self._annotation_type(annotation)
            if annotation is not None
            else _literal_type_of(value)
        )

    def _project_symbol_value(self, dotted: str, ref: SymbolRef, line: int) -> _Value:
        if self._workspace.parsed_class(ref) is not None:
            class_type = self._types.class_type(ref)
            if dotted.rsplit(".", 1)[-1] == ref.sym.rsplit(".", 1)[-1]:
                return _Value(replace(class_type, cat="class"), literal=dotted)
            return _Value(
                class_type if class_type.cat == "enum" else UNKNOWN, literal=dotted
            )
        return self._cached_variable(
            dotted,
            line,
            lambda: self._graph.add("var", dotted, line, target=ref),
            _CALLABLE,
        )

    def _cached_variable(
        self, key: str, line: int, create: Callable[[], _Node], pin_type: PinType
    ) -> _Value:
        cached = self._globals.get(key)
        if cached is not None:
            return cached
        node = create()
        value = self._graph.output(node, key.rsplit(".", 1)[-1], pin_type)
        self._globals[key] = value
        return value

    def _super_value(self) -> _Value:
        owner = self._owner_ref()
        if owner is not None:
            for _, base in self._workspace.base_classes(owner):
                if (
                    isinstance(base, SymbolRef)
                    and self._workspace.parsed_class(base) is not None
                ):
                    return _Value(self._types.class_type(base), literal="super()")
        return _Value(UNKNOWN, literal="super()")

    def _attribute(self, expression: ast.Attribute) -> _Value:
        attributes, base = _split_attribute(expression)
        if (
            isinstance(base, ast.Name)
            and not self._is_local(base.id)
            and base.id not in self._module_variables
        ):
            return self._global_value(
                f"{base.id}.{'.'.join(attributes)}", expression.lineno
            )
        current = self._expr(base)
        prefix = base.id if isinstance(base, ast.Name) else None
        pin_name = _pin_name(base)
        index = 0
        while index < len(attributes):
            end = self._group_end(prefix, attributes, index)
            name = ".".join(attributes[index : end + 1])
            pin_type, annotation = self._attribute_chain_type(
                current, attributes[index : end + 1]
            )
            current = self._break_read(
                current, pin_name, name, pin_type, annotation, expression.lineno
            )
            pin_name = attributes[end]
            prefix = f"{prefix}.{name}" if prefix is not None else None
            index = end + 1
        return current

    def _group_end(
        self, prefix: str | None, attributes: Sequence[str], start: int
    ) -> int:
        if prefix is None:
            return len(attributes) - 1
        first = self._attribute_counts[".".join([prefix, *attributes[: start + 1]])]
        end = start
        while (
            end + 1 < len(attributes)
            and self._attribute_counts[".".join([prefix, *attributes[: end + 2]])]
            == first
        ):
            end += 1
        return end

    def _break_read(
        self,
        base: _Value,
        pin_name: str,
        attribute: str,
        pin_type: PinType,
        annotation: tuple[ast.expr, ParsedModule] | None,
        line: int,
    ) -> _Value:
        key = (base.node, base.pin, base.literal)
        node = self._breaks.get(key)
        if node is None:
            label = _type_name(base.type) or pin_name
            node = self._graph.add(
                "break", f"Break {label}", line, target=base.type.ref
            )
            self._graph.connect(node, pin_name, base)
            self._breaks[key] = node
        existing = node.output(attribute)
        if existing is not None:
            return _Value(existing.type, node.id, existing.name)
        return self._graph.output(node, attribute, pin_type, annotation)

    def _attribute_chain_type(
        self, base: _Value, attributes: Sequence[str]
    ) -> tuple[PinType, tuple[ast.expr, ParsedModule] | None]:
        current = base.type
        annotation: tuple[ast.expr, ParsedModule] | None = None
        for attribute in attributes:
            member = self._member(current, attribute)
            if member is None:
                return UNKNOWN, None
            current, annotation = self._member_type(member), (
                (member.annotation, member.module)
                if member.annotation is not None
                else None
            )
        return current, annotation

    def _member(self, owner: PinType, attribute: str) -> _Member | None:
        if owner.ref is None or self._workspace.parsed_class(owner.ref) is None:
            return None
        return self._class_members(owner.ref).get(attribute)

    def _member_type(self, member: _Member) -> PinType:
        if member.is_method:
            return PinType("method", "callable")
        return (
            self._resolver(member.module).annotation(member.annotation)
            if member.annotation is not None
            else UNKNOWN
        )

    def _class_members(self, ref: SymbolRef) -> dict[str, _Member]:
        cached = self._members.get(ref)
        if cached is not None:
            return cached
        members: dict[str, _Member] = {}
        for ancestor in self._workspace.class_ancestry(ref):
            parsed = self._workspace.parsed_class(ancestor)
            module = self._workspace.module(ancestor.path)
            if parsed is None or module is None:
                continue
            for name, member in _members_of(parsed.node, module).items():
                members.setdefault(name, member)
        self._members[ref] = members
        return members

    def _element_type(self, value: _Value) -> PinType:
        if value.annotation is None:
            return UNKNOWN
        annotation, module = value.annotation
        if isinstance(annotation, ast.Subscript):
            base = (dotted_name(annotation.value) or "").rsplit(".", 1)[-1]
            arguments = (
                annotation.slice.elts
                if isinstance(annotation.slice, ast.Tuple)
                else [annotation.slice]
            )
            if (
                base in _SEQUENCE_ANNOTATIONS
                or base in _MAPPING_ANNOTATIONS
                or base in ("tuple", "Tuple")
            ):
                return self._resolver(module).annotation(arguments[0])
        return UNKNOWN

    def _item_type(self, container: _Value, key: ast.expr) -> PinType:
        if container.annotation is None:
            return UNKNOWN
        annotation, module = container.annotation
        if not isinstance(annotation, ast.Subscript):
            return UNKNOWN
        base = (dotted_name(annotation.value) or "").rsplit(".", 1)[-1]
        arguments = (
            annotation.slice.elts
            if isinstance(annotation.slice, ast.Tuple)
            else [annotation.slice]
        )
        if base in _MAPPING_ANNOTATIONS and len(arguments) == 2:
            return self._resolver(module).annotation(arguments[1])
        if base in _SEQUENCE_ANNOTATIONS and not isinstance(key, ast.Slice):
            return self._resolver(module).annotation(arguments[0])
        if (
            base in ("tuple", "Tuple")
            and isinstance(key, ast.Constant)
            and isinstance(key.value, int)
            and -len(arguments) <= key.value < len(arguments)
        ):
            chosen = (
                arguments[0]
                if len(arguments) == 2 and isinstance(arguments[1], ast.Constant)
                else arguments[key.value]
            )
            return self._resolver(module).annotation(chosen)
        return UNKNOWN

    def _call(
        self,
        call: ast.Call,
        *,
        exec_candidate: bool,
        out_names: Sequence[str],
        awaited: bool = False,
    ) -> list[_Value]:
        callee = self._resolve_callee(call)
        arguments = self._arguments(call, callee)
        node = self._graph.add(
            callee.kind,
            callee.title,
            call.lineno,
            target=callee.target,
            external=callee.external,
            note=callee.note,
        )
        if awaited:
            node.notes.append("awaits")
        if callee.receiver is not None:
            self._graph.connect(node, callee.receiver_name, callee.receiver)
        self._connect_arguments(node, arguments)
        if exec_candidate and not callee.pure:
            self._step(node)
        if not out_names:
            return []
        if callee.kind == "make" and len(out_names) == 1:
            return [
                self._graph.output(
                    node, _short_name(callee.title.removeprefix("Make ")), callee.result
                )
            ]
        if len(out_names) == 1:
            return [self._graph.output(node, out_names[0], callee.result)]
        return [self._graph.output(node, name, UNKNOWN) for name in out_names]

    def _arguments(
        self, call: ast.Call, callee: _Callee, first_fallback: str | None = None
    ) -> list[_Argument]:
        arguments: list[_Argument] = []
        for index, argument in enumerate(call.args):
            if isinstance(argument, ast.Starred):
                name = f"*{_pin_name(argument.value, 'args')}"
            elif index < len(callee.parameters):
                name = callee.parameters[index]
            elif callee.vararg is not None:
                name = f"*{callee.vararg}"
            elif index == 0 and first_fallback is not None:
                name = first_fallback
            else:
                name = _argument_name(argument, index)
            arguments.append(self._argument(name, argument, callee))
        for keyword in call.keywords:
            name = (
                keyword.arg
                if keyword.arg is not None
                else f"**{_pin_name(keyword.value, 'kwargs')}"
            )
            arguments.append(self._argument(name, keyword.value, callee))
        return arguments

    def _argument(self, name: str, expression: ast.expr, callee: _Callee) -> _Argument:
        value = self._expr(expression)
        declared = callee.parameter_types.get(name)
        return _Argument(
            name,
            value,
            declared if declared is not None and declared.cat != "any" else value.type,
        )

    def _connect_arguments(self, node: _Node, arguments: Sequence[_Argument]) -> None:
        for argument in arguments:
            self._graph.connect(node, argument.name, argument.value, argument.pin_type)

    def _resolve_callee(self, call: ast.Call) -> _Callee:
        function = call.func
        if isinstance(function, ast.Name):
            if function.id in self._local_functions:
                return _Callee("ext", function.id, pure=False, note="Local function")
            if self._is_local(function.id):
                return self._local_callee(
                    function.id, self._name_value(function.id, call.lineno)
                )
            return self._global_callee(function.id, call.lineno)
        if isinstance(function, ast.Attribute):
            dotted = dotted_name(function)
            if dotted is not None and not self._is_local(dotted.split(".")[0]):
                return self._global_callee(dotted, call.lineno)
            return self._method_callee(function, self._expr(function.value))
        return _Callee(
            "ext",
            ast.unparse(function),
            pure=False,
            receiver=self._expr(function),
            receiver_name="callable",
        )

    def _local_callee(self, name: str, value: _Value) -> _Callee:
        if (
            value.type.cat == "class"
            and value.type.ref is not None
            and self._workspace.parsed_class(value.type.ref) is not None
        ):
            return self._make_callee(value.type.ref)
        return _Callee("ext", name, pure=False, receiver=value, receiver_name=name)

    def _call_is_pure(self, call: ast.Call) -> bool:
        function = call.func
        if isinstance(function, ast.Name):
            if function.id in self._local_functions:
                return False
            if self._is_local(function.id):
                binding = self._env.get(function.id)
                return (
                    isinstance(binding, _Value)
                    and binding.type.cat == "class"
                    and binding.type.ref is not None
                )
            return self._global_is_pure(function.id)
        if isinstance(function, ast.Attribute):
            dotted = dotted_name(function)
            if dotted is not None and not self._is_local(dotted.split(".")[0]):
                return self._global_is_pure(dotted)
            return function.attr in _PURE_METHODS
        return False

    def _global_is_pure(self, dotted: str) -> bool:
        head, _, rest = dotted.partition(".")
        if head in self._module_variables and rest:
            return dotted.rsplit(".", 1)[-1] in _PURE_METHODS
        resolved = self._workspace.resolve(self._module, dotted)
        if isinstance(resolved, SymbolRef):
            return self._workspace.parsed_class(resolved) is not None and _same_last(
                dotted, resolved.sym
            )
        if isinstance(resolved, ExternalRef):
            return _external_is_pure(_external_name(resolved))
        if (
            resolved is None
            and dotted in _BUILTIN_NAMES
            and dotted not in self._module.imports
        ):
            return dotted in _PURE_BUILTINS or dotted[:1].isupper()
        return False

    def _global_callee(self, dotted: str, line: int) -> _Callee:
        head, _, rest = dotted.partition(".")
        pure = self._global_is_pure(dotted)
        if head in self._module_variables and rest:
            receiver_text, _, method = dotted.rpartition(".")
            receiver_type = (
                self._module_variable_type(head) if receiver_text == head else UNKNOWN
            )
            return self._method_callee_named(
                _receiver_title(dotted),
                method,
                _Value(receiver_type, literal=receiver_text),
                pure=pure,
            )
        resolved = self._workspace.resolve(self._module, dotted)
        if isinstance(resolved, SymbolRef):
            if self._workspace.parsed_class(resolved) is not None and _same_last(
                dotted, resolved.sym
            ):
                return self._make_callee(resolved)
            function = self._workspace.parsed_function(resolved)
            if function is not None:
                return self._function_callee(
                    "call", dotted, resolved, function, pure=pure, bound=False
                )
        if isinstance(resolved, ExternalRef):
            return _Callee("ext", dotted, pure=pure, external=_external_name(resolved))
        if resolved is None and dotted in _BUILTIN_NAMES:
            return _Callee(
                "ext",
                dotted,
                pure=pure,
                parameters=_BUILTIN_PARAMETERS.get(dotted, ()),
                result=_BUILTIN_RESULTS.get(dotted, UNKNOWN),
            )
        return _Callee("ext", dotted, pure=pure)

    def _make_callee(self, ref: SymbolRef) -> _Callee:
        name = ref.sym.rsplit(".", 1)[-1]
        result = self._types.class_type(ref)
        initializer = self._workspace.find_method(ref, "__init__")
        if initializer is not None:
            function = self._workspace.parsed_function(initializer)
            module = self._workspace.module(initializer.path)
            if function is not None and module is not None:
                positional, vararg, parameter_types = self._signature(
                    function.node, module, skip_first=True
                )
                return _Callee(
                    "make",
                    f"Make {name}",
                    pure=True,
                    result=result,
                    target=ref,
                    parameters=positional,
                    vararg=vararg,
                    parameter_types=parameter_types,
                )
        fields = self._class_fields(ref)
        return _Callee(
            "make",
            f"Make {name}",
            pure=True,
            result=result,
            target=ref,
            parameters=tuple(fields),
            parameter_types=fields,
        )

    def _class_fields(self, ref: SymbolRef) -> dict[str, PinType]:
        fields: dict[str, PinType] = {}
        for ancestor in reversed(self._workspace.class_ancestry(ref)):
            parsed = self._workspace.parsed_class(ancestor)
            module = self._workspace.module(ancestor.path)
            if parsed is None or module is None:
                continue
            for statement in parsed.node.body:
                if (
                    isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                    and not _is_class_variable(statement.annotation)
                ):
                    fields[statement.target.id] = self._resolver(module).annotation(
                        statement.annotation
                    )
        return fields

    def _function_callee(
        self,
        kind: str,
        title: str,
        ref: SymbolRef,
        function: ParsedFunction,
        *,
        pure: bool,
        bound: bool,
        receiver: _Value | None = None,
    ) -> _Callee:
        module = self._workspace.module(ref.path)
        if module is None:
            return _Callee(kind, title, pure=pure, target=ref, receiver=receiver)
        decorators = _decorator_names(function.node)
        is_method = (
            function.class_qualname is not None and not decorators & _STATIC_DECORATORS
        )
        skip_first = is_method and (bound or bool(decorators & _CLASS_DECORATORS))
        positional, vararg, parameter_types = self._signature(
            function.node, module, skip_first=skip_first
        )
        result = (
            self._resolver(module).annotation(function.node.returns)
            if function.node.returns is not None
            else UNKNOWN
        )
        return _Callee(
            kind,
            title,
            pure=pure,
            result=result,
            target=ref,
            receiver=receiver,
            parameters=positional,
            vararg=vararg,
            parameter_types=parameter_types,
        )

    def _signature(
        self,
        definition: ast.FunctionDef | ast.AsyncFunctionDef,
        module: ParsedModule,
        *,
        skip_first: bool,
    ) -> tuple[tuple[str, ...], str | None, dict[str, PinType]]:
        arguments = definition.args
        positional = [*arguments.posonlyargs, *arguments.args][1 if skip_first else 0 :]
        resolver = self._resolver(module)
        parameter_types = {
            argument.arg: resolver.annotation(argument.annotation)
            for argument in _all_arguments(arguments)
            if argument.annotation is not None
        }
        vararg = arguments.vararg.arg if arguments.vararg is not None else None
        return tuple(argument.arg for argument in positional), vararg, parameter_types

    def _method_callee(self, function: ast.Attribute, receiver: _Value) -> _Callee:
        return self._method_callee_named(
            _receiver_title(ast.unparse(function), function.value),
            function.attr,
            receiver,
            pure=function.attr in _PURE_METHODS,
        )

    def _method_callee_named(
        self, title: str, method: str, receiver: _Value, *, pure: bool
    ) -> _Callee:
        ref = receiver.type.ref
        found = (
            self._workspace.find_method(ref, method)
            if ref is not None and self._workspace.parsed_class(ref) is not None
            else None
        )
        function = self._workspace.parsed_function(found) if found is not None else None
        if found is not None and function is not None:
            return self._function_callee(
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
            if method in _SAME_TYPE_METHODS and receiver.type.cat != "any"
            else _METHOD_RESULTS.get(method, UNKNOWN)
        )
        return _Callee("method", title, pure=pure, result=result, receiver=receiver)

    def _await(
        self, expression: ast.Await, *, exec_candidate: bool, out_name: str
    ) -> _Value:
        if isinstance(expression.value, ast.Call):
            return self._call(
                expression.value,
                exec_candidate=exec_candidate,
                out_names=(out_name,),
                awaited=True,
            )[0]
        value = self._expr(expression.value)
        node = self._graph.add("ext", "await", expression.lineno, note="awaits")
        self._graph.connect(node, "awaitable", value)
        if exec_candidate:
            self._step(node)
        return self._graph.output(node, out_name, UNKNOWN)

    def _folds(self, expression: ast.expr, *, named: bool) -> bool:
        if isinstance(expression, ast.Name) or _is_literal_expression(expression):
            return False
        if self._folded_parts(expression) is None:
            return False
        computations, operations = self._fold_counts(expression)
        return computations >= 2 or (named and operations >= 1)

    def _expression(self, expression: ast.expr, name: str) -> _Value:
        return self._expression_node(self._fold(expression), name, expression.lineno)

    def _expression_node(self, folded: _Folded, name: str, line: int) -> _Value:
        title = name or ("Check" if folded.result.cat == "bool" else "Calculate")
        node = self._graph.add("expr", title, line)
        self._write_expression(node, folded)
        return self._graph.output(node, "", folded.result)

    def _inline_condition(
        self, expression: ast.expr, create: Callable[[], _Node]
    ) -> _Node:
        folded = self._fold(expression)
        node = create()
        self._write_expression(node, folded)
        return node

    def _write_expression(self, node: _Node, folded: _Folded) -> None:
        node.expression = folded.lines
        for pin, value in folded.inputs:
            self._graph.connect(node, pin, value)

    def _fold(self, expression: ast.expr) -> _Folded:
        inputs: dict[str, _Value] = {}
        values: dict[int, _Value] = {}
        types: dict[int, PinType] = {}
        leaves: dict[int, str] = {}
        self._fold_walk(expression, inputs, values, types, leaves)
        return _Folded(
            list(inputs.items()),
            types.get(id(expression), UNKNOWN),
            _expression_lines(_name_leaves(expression, leaves), _EXPRESSION_WIDTH),
        )

    def _fold_walk(
        self,
        expression: ast.expr,
        inputs: dict[str, _Value],
        values: dict[int, _Value],
        types: dict[int, PinType],
        leaves: dict[int, str],
    ) -> None:
        literal = _literal(expression)
        if literal is not None:
            types[id(expression)] = literal.type
            return
        if isinstance(expression, ast.Name):
            if self._is_local(expression.id):
                value = inputs.get(expression.id) or self._name_value(
                    expression.id, expression.lineno
                )
                inputs[expression.id] = value
                values[id(expression)] = value
                types[id(expression)] = value.type
            else:
                types[id(expression)] = UNKNOWN
            return
        parts = self._folded_parts(expression)
        if parts is None:
            value = self._expr(expression)
            if value.node is not None:
                name = _unique(
                    _shorten(ast.unparse(expression), _INPUT_NAME_LIMIT), set(inputs)
                )
                inputs[name] = value
                leaves[id(expression)] = name
            values[id(expression)] = value
            types[id(expression)] = value.type
            return
        for part in parts:
            self._fold_walk(part, inputs, values, types, leaves)
        types[id(expression)] = self._folded_type(expression, types, values)

    def _on_project_object(self, expression: ast.expr) -> bool:
        root = expression
        while isinstance(root, (ast.Attribute, ast.Subscript)):
            root = root.value
        if not isinstance(root, ast.Name) or not self._is_local(root.id):
            return False
        binding = self._env.get(root.id)
        return isinstance(binding, _Value) and binding.type.ref is not None

    def _folded_parts(self, expression: ast.expr) -> list[ast.expr] | None:
        if isinstance(expression, ast.BoolOp):
            return list(expression.values)
        if isinstance(expression, ast.BinOp):
            return [expression.left, expression.right]
        if isinstance(expression, ast.UnaryOp):
            return [expression.operand]
        if isinstance(expression, ast.Compare):
            return [expression.left, *expression.comparators]
        if isinstance(expression, ast.IfExp):
            return [expression.test, expression.body, expression.orelse]
        if isinstance(expression, ast.Attribute):
            dotted = dotted_name(expression)
            if dotted is not None and not self._is_local(dotted.split(".")[0]):
                return []
            if self._on_project_object(expression):
                return None
            return [expression.value]
        if isinstance(expression, ast.Subscript):
            return [expression.value, expression.slice]
        if isinstance(expression, ast.Slice):
            return [
                part
                for part in (expression.lower, expression.upper, expression.step)
                if part is not None
            ]
        if isinstance(expression, (ast.Tuple, ast.List, ast.Set)):
            if any(isinstance(element, ast.Starred) for element in expression.elts):
                return None
            return list(expression.elts)
        if isinstance(expression, ast.Call) and self._folds_call(expression):
            return [
                *self._method_receiver(expression.func),
                *expression.args,
                *(keyword.value for keyword in expression.keywords),
            ]
        return None

    def _method_receiver(self, function: ast.expr) -> list[ast.expr]:
        if not isinstance(function, ast.Attribute):
            return []
        dotted = dotted_name(function)
        if dotted is not None and not self._is_local(dotted.split(".")[0]):
            return []
        return [function.value]

    def _folds_call(self, call: ast.Call) -> bool:
        if any(isinstance(argument, ast.Starred) for argument in call.args) or any(
            keyword.arg is None for keyword in call.keywords
        ):
            return False
        function = call.func
        if isinstance(function, ast.Name):
            return not self._is_local(function.id) and self._global_folds(function.id)
        if isinstance(function, ast.Attribute):
            dotted = dotted_name(function)
            if dotted is not None and not self._is_local(dotted.split(".")[0]):
                return self._global_folds(dotted)
            return function.attr in _PURE_METHODS and not self._on_project_object(
                function.value
            )
        return False

    def _global_folds(self, dotted: str) -> bool:
        if dotted.rsplit(".", 1)[-1][:1].isupper():
            return False
        if isinstance(self._workspace.resolve(self._module, dotted), SymbolRef):
            return False
        return self._global_is_pure(dotted)

    def _fold_counts(self, expression: ast.expr) -> tuple[int, int]:
        if isinstance(expression, ast.Name) or _is_literal_expression(expression):
            return 0, 0
        parts = self._folded_parts(expression)
        if parts is None:
            return 0, 0
        computations = int(isinstance(expression, _COMPUTATIONS))
        operations = int(isinstance(expression, _OPERATIONS))
        for part in parts:
            more, extra = self._fold_counts(part)
            computations += more
            operations += extra
        return computations, operations

    def _folded_type(
        self,
        expression: ast.expr,
        types: dict[int, PinType],
        values: dict[int, _Value],
    ) -> PinType:
        def of(part: ast.expr) -> PinType:
            return types.get(id(part), UNKNOWN)

        if isinstance(expression, ast.Compare):
            return _BOOL
        if isinstance(expression, ast.BoolOp):
            parts = [of(value) for value in expression.values]
            return _BOOL if all(part.cat == "bool" for part in parts) else parts[0]
        if isinstance(expression, ast.UnaryOp):
            return (
                _BOOL if isinstance(expression.op, ast.Not) else of(expression.operand)
            )
        if isinstance(expression, ast.BinOp):
            left, right = of(expression.left), of(expression.right)
            if left.cat != "any" and left.cat == right.cat:
                return left
            if {left.cat, right.cat} == {"int", "float"}:
                return _FLOAT
            return left if left.cat == "str" else UNKNOWN
        if isinstance(expression, ast.IfExp):
            body, orelse = of(expression.body), of(expression.orelse)
            return body if body.cat == orelse.cat else UNKNOWN
        if isinstance(expression, ast.Call):
            return self._folded_call_type(expression, types)
        if isinstance(expression, ast.Subscript):
            container = values.get(id(expression.value))
            return (
                self._item_type(container, expression.slice)
                if container is not None
                else UNKNOWN
            )
        return UNKNOWN

    def _folded_call_type(self, call: ast.Call, types: dict[int, PinType]) -> PinType:
        dotted = dotted_name(call.func) or ""
        if dotted in _BUILTIN_RESULTS:
            return _BUILTIN_RESULTS[dotted]
        resolved = self._workspace.resolve(self._module, dotted) if dotted else None
        if (
            isinstance(resolved, ExternalRef)
            and _external_name(resolved).split(".")[0] in _NUMERIC_MODULES
            and call.args
        ):
            first = types.get(id(call.args[0]), UNKNOWN)
            return first if first.cat in ("int", "float") else UNKNOWN
        return UNKNOWN

    def _operation(
        self,
        title: str,
        line: int,
        inputs: Sequence[tuple[str, _Value]],
        result: PinType,
    ) -> _Value:
        node = self._graph.add("op", title, line)
        for name, value in inputs:
            self._graph.connect(node, name, value)
        return self._graph.output(node, "", result)

    def _bool_op(self, expression: ast.BoolOp) -> _Value:
        values = [self._expr(value) for value in expression.values]
        result = (
            _BOOL
            if all(value.type.cat == "bool" for value in values)
            else values[0].type
        )
        title = "AND" if isinstance(expression.op, ast.And) else "OR"
        return self._operation(
            title,
            expression.lineno,
            [(_letter(index), value) for index, value in enumerate(values)],
            result,
        )

    def _binary(self, expression: ast.BinOp) -> _Value:
        left = self._expr(expression.left)
        right = self._expr(expression.right)
        result = (
            left.type
            if left.type.cat != "any" and left.type.cat == right.type.cat
            else (left.type if left.type.cat == "str" else UNKNOWN)
        )
        return self._operation(
            _OPERATORS.get(type(expression.op), "?"),
            expression.lineno,
            [("a", left), ("b", right)],
            result,
        )

    def _unary(self, expression: ast.UnaryOp) -> _Value:
        operand = self._expr(expression.operand)
        result = _BOOL if isinstance(expression.op, ast.Not) else operand.type
        return self._operation(
            _UNARY.get(type(expression.op), "?"),
            expression.lineno,
            [("value", operand)],
            result,
        )

    def _compare(self, expression: ast.Compare) -> _Value:
        if (
            len(expression.ops) == 1
            and isinstance(expression.ops[0], (ast.Is, ast.IsNot))
            and _is_none(expression.comparators[0])
        ):
            title = (
                "is None" if isinstance(expression.ops[0], ast.Is) else "is not None"
            )
            return self._operation(
                title,
                expression.lineno,
                [("value", self._expr(expression.left))],
                _BOOL,
            )
        operands = [
            self._expr(expression.left),
            *(self._expr(comparator) for comparator in expression.comparators),
        ]
        symbols = [_COMPARISONS.get(type(op), "?") for op in expression.ops]
        if len(symbols) == 1:
            title = symbols[0]
        else:
            title = (
                " ".join(
                    part
                    for index, symbol in enumerate(symbols)
                    for part in (_letter(index), symbol)
                )
                + f" {_letter(len(symbols))}"
            )
        return self._operation(
            title,
            expression.lineno,
            [(_letter(index), value) for index, value in enumerate(operands)],
            _BOOL,
        )

    def _subscript(self, expression: ast.Subscript) -> _Value:
        container = self._expr(expression.value)
        container_name = _pin_name(expression.value)
        result = self._item_type(container, expression.slice)
        key = expression.slice
        if isinstance(key, ast.Slice):
            parts = [
                (name, part)
                for name, part in (
                    ("lower", key.lower),
                    ("upper", key.upper),
                    ("step", key.step),
                )
                if part is not None
            ]
            inputs = [
                (container_name, container),
                *((name, self._expr(part)) for name, part in parts),
            ]
            return self._operation(
                f"[{ast.unparse(key)}]",
                expression.lineno,
                inputs,
                container.type if result is UNKNOWN else result,
            )
        key_value = self._expr(key)
        if key_value.literal is not None and len(key_value.literal) <= 20:
            return self._operation(
                f"[{key_value.literal}]",
                expression.lineno,
                [(container_name, container)],
                result,
            )
        return self._operation(
            "[ ]",
            expression.lineno,
            [(container_name, container), ("key", key_value)],
            result,
        )

    def _format_text(self, expression: ast.JoinedStr) -> _Value:
        pieces: dict[str, _Value] = {}
        for part in expression.values:
            if isinstance(part, ast.FormattedValue):
                text = _shorten(ast.unparse(part.value), 30)
                if text not in pieces:
                    pieces[text] = self._expr(part.value)
        node = self._graph.add(
            "make", "Format text", expression.lineno, code=ast.unparse(expression)
        )
        for name, value in pieces.items():
            self._graph.connect(node, name, value)
        return self._graph.output(node, "", _STR)

    def _collection(
        self, expression: ast.Tuple | ast.List | ast.Set | ast.Dict
    ) -> _Value:
        if isinstance(expression, ast.Dict):
            return self._dictionary(expression)
        kind_name, result = {
            ast.Tuple: ("tuple", _TUPLE),
            ast.List: ("list", _LIST),
            ast.Set: ("set", _SET),
        }[type(expression)]
        inputs: list[tuple[str, _Value]] = []
        for index, element in enumerate(expression.elts):
            if isinstance(element, ast.Starred):
                inputs.append(
                    (f"*{_pin_name(element.value, 'items')}", self._expr(element.value))
                )
            else:
                inputs.append((_element_name(element, index), self._expr(element)))
        node = self._graph.add("make", f"Make {kind_name}", expression.lineno)
        for name, value in inputs:
            self._graph.connect(node, name, value)
        return self._graph.output(node, kind_name, result)

    def _dictionary(self, expression: ast.Dict) -> _Value:
        inputs: list[tuple[str, _Value]] = []
        for index, (key, value) in enumerate(zip(expression.keys, expression.values)):
            if key is None:
                inputs.append((f"**{_pin_name(value, 'mapping')}", self._expr(value)))
            elif isinstance(key, ast.Constant) and isinstance(key.value, str):
                inputs.append((key.value or '""', self._expr(value)))
            else:
                inputs.append((f"key {index + 1}", self._expr(key)))
                inputs.append((f"value {index + 1}", self._expr(value)))
        node = self._graph.add("make", "Make dict", expression.lineno)
        for name, entry in inputs:
            self._graph.connect(node, name, entry)
        return self._graph.output(node, "dict", _DICT)

    def _opaque(
        self, expression: ast.expr, title: str, result: PinType, *, code: str | None
    ) -> _Value:
        inputs = [
            (name, self._name_value(name, expression.lineno))
            for name in _free_names(expression)
            if name in self._env or name in self._module_variables
        ]
        node = self._graph.add("ext", title, expression.lineno, code=code)
        for name, value in inputs:
            self._graph.connect(node, name, value)
        return self._graph.output(node, "", result)

    def _annotation_type(self, annotation: ast.expr | None) -> PinType:
        return (
            self._resolver(self._module).annotation(annotation)
            if annotation is not None
            else UNKNOWN
        )

    def _resolver(self, module: ParsedModule) -> TypeResolver:
        resolver = self._resolvers.get(module.path)
        if resolver is None or resolver.module is not module:
            resolver = self._types.resolver(module)
            self._resolvers[module.path] = resolver
        return resolver


def _returned(outcome: _Outcome) -> _Value:
    return (
        outcome.value
        if outcome.terminated and outcome.value is not None
        else _none_literal()
    )


def _none_literal() -> _Value:
    return _Value(_NONE, literal="None")


def _differ(true_env: _Environment, false_env: _Environment) -> bool:
    return any(
        name in false_env and true_env[name] != false_env[name] for name in true_env
    )


def _name_leaves(expression: ast.expr, leaves: dict[int, str]) -> ast.expr:
    memo: dict[int, Any] = {}
    copied = copy.deepcopy(expression, memo)
    named = {id(memo[key]): name for key, name in leaves.items() if key in memo}
    renamed: ast.expr = _LeafNamer(named).visit(copied)
    return renamed


class _LeafNamer(ast.NodeTransformer):
    def __init__(self, names: dict[int, str]) -> None:
        self.names = names

    def visit(self, node: ast.AST) -> Any:
        name = self.names.get(id(node))
        return ast.Name(name) if name is not None else super().visit(node)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, str) and len(node.value) > _LITERAL_LIMIT:
            return ast.Name(
                _shorten(json.dumps(node.value, ensure_ascii=False), _LITERAL_LIMIT)
            )
        return node


def _expression_lines(expression: ast.expr, width: int) -> list[str]:
    text = _expression_text(expression)
    if len(text) > width and isinstance(expression, ast.Call):
        return _call_lines(expression, width)
    if len(text) > width and isinstance(expression, (ast.Tuple, ast.List, ast.Set)):
        return _collection_lines(expression, width)
    if len(text) > width and isinstance(expression, ast.UnaryOp):
        prefix = _unary_prefix(expression)
        inner = _expression_lines(expression.operand, max(16, width - len(prefix)))
        if _precedence(expression.operand) < _precedence(expression):
            inner = _parenthesised(inner)
        return [prefix + inner[0], *(" " * len(prefix) + line for line in inner[1:])]
    pieces = _expression_pieces(expression) if len(text) > width else None
    if pieces is None:
        return [text]
    lines: list[str] = []
    for prefix, piece, minimum in pieces:
        inner = _expression_lines(piece, max(16, width - len(prefix) - 1))
        if _precedence(piece) < minimum:
            inner = _parenthesised(inner)
        lines.append(prefix + inner[0])
        lines += [" " * len(prefix) + line for line in inner[1:]]
    return lines


def _call_lines(call: ast.Call, width: int) -> list[str]:
    lines = [f"{_expression_text(call.func)}("]
    arguments = [("", argument) for argument in call.args] + [
        (f"{keyword.arg}=", keyword.value) for keyword in call.keywords
    ]
    for prefix, argument in arguments:
        inner = _expression_lines(argument, max(16, width - 4 - len(prefix)))
        lines.append(f"    {prefix}{inner[0]}")
        lines += [f"    {' ' * len(prefix)}{line}" for line in inner[1:]]
        lines[-1] += ","
    lines.append(")")
    return lines


def _collection_lines(
    collection: ast.Tuple | ast.List | ast.Set, width: int
) -> list[str]:
    brackets = {ast.List: ("[", "]"), ast.Set: ("{", "}")}
    opening, closing = brackets.get(type(collection), ("(", ")"))
    lines = [opening]
    for element in collection.elts:
        inner = _expression_lines(element, max(16, width - 4))
        lines += [f"    {line}" for line in inner]
        lines[-1] += ","
    lines.append(closing)
    return lines


def _expression_text(expression: ast.expr) -> str:
    if isinstance(expression, ast.Call) and not any(
        isinstance(argument, ast.Starred) for argument in expression.args
    ):
        arguments = [_expression_text(argument) for argument in expression.args] + [
            (
                f"{keyword.arg}={_expression_text(keyword.value)}"
                if keyword.arg is not None
                else f"**{_expression_text(keyword.value)}"
            )
            for keyword in expression.keywords
        ]
        return f"{_expression_text(expression.func)}({', '.join(arguments)})"
    if isinstance(expression, ast.UnaryOp) and not _is_literal_expression(expression):
        operand = _expression_text(expression.operand)
        if _precedence(expression.operand) < _precedence(expression):
            operand = f"({operand})"
        return _unary_prefix(expression) + operand
    pieces = _expression_pieces(expression)
    if pieces is None:
        return ast.unparse(expression)
    return " ".join(
        prefix
        + (
            f"({_expression_text(piece)})"
            if _precedence(piece) < minimum
            else _expression_text(piece)
        )
        for prefix, piece, minimum in pieces
    )


def _expression_pieces(
    expression: ast.expr,
) -> list[tuple[str, ast.expr, int]] | None:
    if isinstance(expression, ast.BoolOp):
        word, level = _PYTHON_OPERATORS[type(expression.op)]
        return [
            ("" if index == 0 else f"{word} ", value, level + 1)
            for index, value in enumerate(expression.values)
        ]
    if isinstance(expression, ast.BinOp) and not isinstance(expression.op, ast.Pow):
        level = _precedence(expression)
        terms: list[tuple[str, ast.expr]] = []
        current: ast.expr = expression
        while isinstance(current, ast.BinOp) and _precedence(current) == level:
            terms.append((f"{_PYTHON_OPERATORS[type(current.op)][0]} ", current.right))
            current = current.left
        terms.reverse()
        return [("", current, level)] + [
            (prefix, term, level + 1) for prefix, term in terms
        ]
    if isinstance(expression, ast.IfExp):
        return [
            ("", expression.body, 1),
            ("if ", expression.test, 1),
            ("else ", expression.orelse, 0),
        ]
    if isinstance(expression, ast.Compare):
        return [("", expression.left, _COMPARE_PRECEDENCE + 1)] + [
            (f"{_PYTHON_COMPARISONS[type(op)]} ", comparator, _COMPARE_PRECEDENCE + 1)
            for op, comparator in zip(expression.ops, expression.comparators)
        ]
    return None


def _unary_prefix(expression: ast.UnaryOp) -> str:
    return (
        "not "
        if isinstance(expression.op, ast.Not)
        else ast.unparse(ast.UnaryOp(expression.op, ast.Name("x"))).removesuffix("x")
    )


def _precedence(expression: ast.expr) -> int:
    if isinstance(expression, (ast.BoolOp, ast.BinOp)):
        return _PYTHON_OPERATORS[type(expression.op)][1]
    if isinstance(expression, ast.Compare):
        return _COMPARE_PRECEDENCE
    if isinstance(expression, ast.UnaryOp):
        return 3 if isinstance(expression.op, ast.Not) else 11
    if isinstance(expression, (ast.IfExp, ast.Lambda, ast.NamedExpr)):
        return 0
    return 13


def _parenthesised(lines: list[str]) -> list[str]:
    if len(lines) == 1:
        return [f"({lines[0]})"]
    return [f"({lines[0]}", *(f" {line}" for line in lines[1:-1]), f" {lines[-1]})"]


def _select_type(when_true: _Value, when_false: _Value) -> PinType:
    if when_true.type.cat == "none" and when_false.type.cat not in ("none", "any"):
        return replace(when_false.type, opt=True)
    if when_false.type.cat == "none" and when_true.type.cat not in ("none", "any"):
        return replace(when_true.type, opt=True)
    return when_true.type if when_true.type.cat != "any" else when_false.type


def _literal(expression: ast.expr) -> _Value | None:
    if not _is_literal_expression(expression):
        return None
    if isinstance(expression, ast.Constant):
        if isinstance(expression.value, str):
            return _Value(
                _STR,
                literal=_shorten(
                    json.dumps(expression.value, ensure_ascii=False), _LITERAL_LIMIT
                ),
            )
        if expression.value is Ellipsis:
            return _Value(UNKNOWN, literal="...")
        return _Value(
            literal_type(expression.value),
            literal=_shorten(ast.unparse(expression), _LITERAL_LIMIT),
        )
    text = ast.unparse(expression)
    if len(text) > _LITERAL_LIMIT:
        return None
    if isinstance(expression, ast.UnaryOp) and isinstance(
        expression.operand, ast.Constant
    ):
        return _Value(literal_type(expression.operand.value), literal=text)
    container_types: dict[type[ast.expr], PinType] = {
        ast.Tuple: _TUPLE,
        ast.List: _LIST,
        ast.Set: _SET,
        ast.Dict: _DICT,
    }
    return _Value(container_types.get(type(expression), UNKNOWN), literal=text)


def _is_literal_expression(expression: ast.expr | None) -> bool:
    if isinstance(expression, ast.Constant):
        return True
    if isinstance(expression, ast.UnaryOp) and isinstance(
        expression.op, (ast.USub, ast.UAdd)
    ):
        return isinstance(expression.operand, ast.Constant) and isinstance(
            expression.operand.value, (int, float, complex)
        )
    if isinstance(expression, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_literal_expression(element) for element in expression.elts)
    if isinstance(expression, ast.Slice):
        return all(
            part is None or _is_literal_expression(part)
            for part in (expression.lower, expression.upper, expression.step)
        )
    if isinstance(expression, ast.Dict):
        return all(
            key is not None and _is_literal_expression(key) for key in expression.keys
        ) and all(_is_literal_expression(value) for value in expression.values)
    return False


def _literal_type_of(value: ast.expr | None) -> PinType:
    literal = _literal(value) if value is not None else None
    return literal.type if literal is not None else UNKNOWN


def _shorten(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _unique(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    counter = 2
    while f"{name} {counter}" in taken:
        counter += 1
    return f"{name} {counter}"


def _unique_labels(labels: Sequence[str]) -> list[str]:
    unique: list[str] = []
    for label in labels:
        unique.append(_unique(label, set(unique)))
    return unique


def _letter(index: int) -> str:
    return chr(ord("a") + index) if index < 26 else f"v{index + 1}"


def _source_title(statement: ast.stmt) -> str:
    try:
        text = ast.unparse(statement)
    except Exception:
        text = type(statement).__name__
    return text.splitlines()[0] if text else type(statement).__name__


def _pin_name(expression: ast.expr, fallback: str = "value") -> str:
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        return expression.attr
    return fallback


def _argument_name(argument: ast.expr, index: int) -> str:
    if isinstance(argument, (ast.Name, ast.Attribute)):
        return _pin_name(argument)
    return f"arg{index + 1}"


def _element_name(element: ast.expr, index: int) -> str:
    return (
        _pin_name(element)
        if isinstance(element, (ast.Name, ast.Attribute))
        else str(index)
    )


def _target_label(target: ast.expr) -> str:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Starred):
        return f"*{_target_label(target.value)}"
    return _shorten(ast.unparse(target), _LABEL_LIMIT)


def _flat_targets(target: ast.expr) -> list[ast.expr]:
    if isinstance(target, (ast.Tuple, ast.List)):
        return [leaf for element in target.elts for leaf in _flat_targets(element)]
    return [target]


def _assigned_names(target: ast.expr) -> list[str] | None:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        names = _assigned_names(target.value)
        return [f"*{name}" for name in names] if names is not None else None
    if isinstance(target, (ast.Tuple, ast.List)):
        collected: list[str] = []
        for element in target.elts:
            names = _assigned_names(element)
            if names is None:
                return None
            collected.extend(names)
        return collected
    return None


def _unwrap_call(value: ast.expr) -> tuple[ast.Call | None, bool]:
    if isinstance(value, ast.Call):
        return value, False
    if isinstance(value, ast.Await) and isinstance(value.value, ast.Call):
        return value.value, True
    return None, False


def _split_attribute(expression: ast.Attribute) -> tuple[list[str], ast.expr]:
    attributes: list[str] = []
    current: ast.expr = expression
    while isinstance(current, ast.Attribute):
        attributes.insert(0, current.attr)
        current = current.value
    return attributes, current


def _receiver_title(text: str, receiver: ast.expr | None = None) -> str:
    if receiver is not None and _is_super_call(receiver):
        return f"super().{text.rsplit('.', 1)[-1]}"
    if receiver is not None and dotted_name(receiver) is None:
        return text.rsplit(".", 1)[-1]
    parts = text.split(".")
    return ".".join(parts[-2:])


def _is_super_call(expression: ast.expr) -> bool:
    return (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Name)
        and expression.func.id == "super"
    )


def _is_none(expression: ast.expr) -> bool:
    return isinstance(expression, ast.Constant) and expression.value is None


def _same_last(dotted: str, sym: str) -> bool:
    return dotted.rsplit(".", 1)[-1] == sym.rsplit(".", 1)[-1]


def _short_name(text: str) -> str:
    return text.rsplit(".", 1)[-1]


def _type_name(pin_type: PinType) -> str | None:
    if pin_type.ref is not None:
        return pin_type.ref.sym.rsplit(".", 1)[-1]
    if pin_type.cat == "any":
        return None
    if (
        pin_type.opt
        and pin_type.label.startswith("Optional[")
        and pin_type.label.endswith("]")
    ):
        return pin_type.label[len("Optional[") : -1]
    return pin_type.label


def _external_name(resolved: ExternalRef) -> str:
    return f"{resolved.module}.{resolved.name}" if resolved.name else resolved.module


def _external_is_pure(external: str) -> bool:
    return (
        external in _PURE_EXTERNALS
        or external.split(".")[0] in _PURE_EXTERNAL_MODULES
        or external.rsplit(".", 1)[-1][:1].isupper()
    )


def _is_class_variable(annotation: ast.expr) -> bool:
    target = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    return (dotted_name(target) or "").rsplit(".", 1)[-1] == "ClassVar"


def _decorator_names(definition: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    for decorator in definition.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = dotted_name(target)
        if name is not None:
            names.add(name.rsplit(".", 1)[-1])
    return names


def _all_arguments(arguments: ast.arguments) -> list[ast.arg]:
    collected = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    if arguments.vararg is not None:
        collected.append(arguments.vararg)
    if arguments.kwarg is not None:
        collected.append(arguments.kwarg)
    return collected


def _members_of(node: ast.ClassDef, module: ParsedModule) -> dict[str, _Member]:
    members: dict[str, _Member] = {}
    for statement in node.body:
        if isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            members.setdefault(
                statement.target.id, _Member(statement.annotation, module)
            )
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _decorator_names(statement) & _PROPERTY_DECORATORS:
                members.setdefault(statement.name, _Member(statement.returns, module))
            else:
                members.setdefault(
                    statement.name, _Member(None, module, is_method=True)
                )
    initializer = next(
        (
            statement
            for statement in node.body
            if isinstance(statement, ast.FunctionDef) and statement.name == "__init__"
        ),
        None,
    )
    if initializer is not None:
        for name, annotation in _initializer_assignments(initializer):
            members.setdefault(name, _Member(annotation, module))
    return members


def _initializer_assignments(
    initializer: ast.FunctionDef,
) -> Iterator[tuple[str, ast.expr | None]]:
    parameters = {
        argument.arg: argument.annotation
        for argument in _all_arguments(initializer.args)
    }
    for statement in ast.walk(initializer):
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Attribute)
            and _is_self(statement.target.value)
        ):
            yield statement.target.attr, statement.annotation
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Attribute) and _is_self(target.value):
                    yield target.attr, (
                        parameters.get(statement.value.id)
                        if isinstance(statement.value, ast.Name)
                        else None
                    )


def _is_self(expression: ast.expr) -> bool:
    return isinstance(expression, ast.Name) and expression.id == "self"


def _module_variables(
    module: ParsedModule,
) -> dict[str, tuple[ast.expr | None, ast.expr | None]]:
    variables: dict[str, tuple[ast.expr | None, ast.expr | None]] = {}
    pending: list[ast.stmt] = list(module.tree.body)
    while pending:
        statement = pending.pop(0)
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                for name in _assigned_names(target) or []:
                    variables.setdefault(name.lstrip("*"), (None, statement.value))
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            variables[statement.target.id] = (statement.annotation, statement.value)
        elif isinstance(statement, ast.If):
            pending.extend([*statement.body, *statement.orelse])
        elif isinstance(statement, ast.Try):
            pending.extend(
                [
                    *statement.body,
                    *statement.orelse,
                    *statement.finalbody,
                    *(item for handler in statement.handlers for item in handler.body),
                ]
            )
    for name in module.top_level:
        variables.pop(name, None)
    return variables


def _local_names(definition: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    names = {argument.arg for argument in _all_arguments(definition.args)}
    pending: list[ast.AST] = list(definition.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            continue
        if isinstance(
            node,
            (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp),
        ):
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
        pending.extend(ast.iter_child_nodes(node))
    return frozenset(names)


def _attribute_counts(
    definition: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in ast.walk(definition):
        if isinstance(node, ast.Attribute):
            name = dotted_name(node)
            if name is not None:
                counts[name] += 1
    return counts


def _free_names(expression: ast.expr) -> list[str]:
    bound: set[str] = set()
    for node in ast.walk(expression):
        if isinstance(node, ast.comprehension):
            bound.update(
                child.id
                for child in ast.walk(node.target)
                if isinstance(child, ast.Name)
            )
        elif isinstance(node, ast.Lambda):
            bound.update(argument.arg for argument in _all_arguments(node.args))
        elif isinstance(node, ast.NamedExpr):
            bound.add(node.target.id)
    names: list[str] = []
    for node in ast.walk(expression):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id not in bound
            and node.id not in names
        ):
            names.append(node.id)
    return names


def _pattern_captures(pattern: ast.pattern) -> list[str]:
    names: list[str] = []
    for node in ast.walk(pattern):
        if (
            isinstance(node, (ast.MatchAs, ast.MatchStar))
            and node.name
            and node.name not in names
        ):
            names.append(node.name)
        elif (
            isinstance(node, ast.MatchMapping) and node.rest and node.rest not in names
        ):
            names.append(node.rest)
    return names


def _suspends(expression: ast.expr) -> bool:
    return any(
        isinstance(node, (ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr))
        for node in ast.walk(expression)
    )


def _contains_return(statements: Sequence[ast.stmt]) -> bool:
    pending: list[ast.AST] = list(statements)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Return):
            return True
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        pending.extend(ast.iter_child_nodes(node))
    return False


def _always_terminates(statements: Sequence[ast.stmt]) -> bool:
    return any(_terminates(statement) for statement in statements)


def _terminates(statement: ast.stmt) -> bool:
    if isinstance(statement, (ast.Return, ast.Raise)):
        return True
    if isinstance(statement, ast.If):
        return _always_terminates(statement.body) and _always_terminates(
            statement.orelse
        )
    return False
