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
from code_blueprints.analysis import model as m
from code_blueprints.analysis.workspace import (
    ExternalRef,
    ModuleRef,
    ParsedFunction,
    ParsedModule,
    SymbolRef,
)
from code_blueprints.languages.language import Language, Profile

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

_COMPARISONS: dict[str, str] = {
    "==": "==",
    "!=": "!=",
    "<": "<",
    "<=": "≤",
    ">": ">",
    ">=": "≥",
    "is": "is",
    "is not": "is not",
    "in": "in",
    "not in": "not in",
    "===": "===",
    "!==": "!==",
    "instanceof": "instanceof",
}
_UNARY: dict[str, str] = {"not": "NOT", "-": "-", "+": "+", "~": "~"}
_LOGICAL: dict[str, str] = {"and": "AND", "or": "OR", "??": "??"}
_COMPUTATIONS = (
    m.Logical,
    m.Binary,
    m.Unary,
    m.Compare,
    m.Conditional,
    m.Call,
    m.Subscript,
)
_OPERATIONS = (m.Logical, m.Binary, m.Unary, m.Compare)


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
    annotation: tuple[m.TypeExpr, ParsedModule] | None = field(
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
        annotation: tuple[m.TypeExpr, ParsedModule] | None = None,
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
    receiver_name: str = ""
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
    annotation: m.TypeExpr | None
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
        self._language: Language = module.language
        self._profile: Profile = module.language.profile
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
        self._local_names = m.bound_names(function.node)
        self._parameter_annotations = {
            parameter.name: parameter.annotation
            for parameter in function.node.params
            if parameter.annotation is not None
        }
        self._attribute_counts = _attribute_counts(function.node)
        self._module_variables = _module_variables(module)
        self._printer = _Printer(module.language)
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
        self._native_labels(graph)
        if self._truncated:
            graph["truncated"] = True
        return graph

    def _entry(self) -> _Node:
        function = self._function.node
        node = self._graph.add("entry", function.name, function.line)
        owner = self._owner_ref()
        if function.implicit_receiver is not None and owner is not None:
            self._env[function.implicit_receiver] = self._graph.output(
                node, function.implicit_receiver, self._types.class_type(owner)
            )
        index = 0
        for parameter in function.params:
            if parameter.kind in ("positional_only", "positional"):
                self._bind_parameter(
                    node,
                    parameter.name,
                    parameter.name,
                    self._parameter_type(parameter, index),
                )
                index += 1
        for parameter in function.params:
            if parameter.kind == "variadic":
                inner = self._annotation_type(parameter.annotation)
                self._bind_parameter(
                    node,
                    parameter.name,
                    f"{self._profile.spread_prefix}{parameter.name}",
                    PinType(self._profile.variadic_label.format(inner.label), "list"),
                )
        for parameter in function.params:
            if parameter.kind == "keyword_only":
                self._bind_parameter(
                    node,
                    parameter.name,
                    parameter.name,
                    self._parameter_type(parameter, -1),
                )
        for parameter in function.params:
            if parameter.kind == "variadic_keyword":
                inner = self._annotation_type(parameter.annotation)
                self._bind_parameter(
                    node,
                    parameter.name,
                    f"{self._profile.mapping_spread_prefix}{parameter.name}",
                    PinType(self._profile.keywords_label.format(inner.label), "map"),
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

    def _parameter_type(self, parameter: m.Parameter, index: int) -> PinType:
        owner = self._owner_ref()
        function = self._function.node
        if (
            index == 0
            and owner is not None
            and parameter.annotation is None
            and function.implicit_receiver is None
        ):
            if function.binding == "static":
                return UNKNOWN
            owner_type = self._types.class_type(owner)
            if function.binding == "class":
                return replace(
                    owner_type, cat="class", label=f"type[{owner_type.label}]"
                )
            return owner_type
        return self._annotation_type(parameter.annotation)

    def _owner_ref(self) -> SymbolRef | None:
        qualname = self._function.class_qualname
        return SymbolRef(self._module.path, qualname) if qualname is not None else None

    def _mark_truncated(self) -> None:
        self._truncated = True
        last_line = (
            self._graph.nodes[-1].line
            if self._graph.nodes
            else self._function.node.line
        )
        marker = self._graph.add_unbounded(
            "return",
            "Truncated",
            last_line,
            note=f"Graph stopped after {MAX_NODES} nodes",
        )
        if any(node.exec_in or node.exec_out for node in self._graph.nodes):
            self._step(marker)

    def _run_block(self, statements: Sequence[m.Stmt], *, function_level: bool) -> None:
        for index, statement in enumerate(statements):
            rest = statements[index:]
            if isinstance(statement, m.If) and self._starts_return_region(
                rest, function_level=function_level
            ):
                self._return_region(rest)
                return
            self._statement(statement)

    def _statement(self, statement: m.Stmt) -> None:
        try:
            self._dispatch_statement(statement)
        except _GraphFull:
            raise
        except Exception as error:
            node = self._graph.add(
                "ext",
                self._source_title(statement),
                statement.line,
                note=f"Not drawn: {type(error).__name__}",
            )
            self._step(node)

    def _dispatch_statement(self, statement: m.Stmt) -> None:
        if isinstance(statement, m.ExprStmt):
            self._expression_statement(statement.value)
        elif isinstance(statement, m.Assign):
            self._assign(statement, exec_candidate=True)
        elif isinstance(statement, m.AugAssign):
            self._augmented_assign(statement)
        elif isinstance(statement, m.Return):
            value = (
                self._expr(statement.value, exec_candidate=True)
                if statement.value is not None
                else None
            )
            self._emit_return(value, statement.line)
        elif isinstance(statement, m.If):
            self._if(statement)
        elif isinstance(statement, m.For):
            self._for(statement)
        elif isinstance(statement, m.While):
            self._while(statement)
        elif isinstance(statement, m.With):
            self._with(statement)
        elif isinstance(statement, m.Try):
            self._try(statement)
        elif isinstance(statement, m.Raise):
            self._raise(statement)
        elif isinstance(statement, m.Match):
            self._match(statement)
        elif isinstance(statement, m.Assert):
            self._assert(statement)
        elif isinstance(statement, m.Delete):
            self._delete(statement)
        elif isinstance(statement, m.Break):
            if self._loop_exits:
                self._loop_exits[-1].extend(self._tails)
            self._tails = []
        elif isinstance(statement, m.Continue):
            self._tails = []
        elif isinstance(statement, m.Global):
            self._declared_globals.update(statement.names)
        elif isinstance(statement, (m.FunctionDef, m.ClassDef)):
            name = _definition_name(statement)
            self._local_functions.add(name)
            self._env.pop(name, None)
        elif isinstance(statement, (m.Pass, m.Import)):
            return
        else:
            self._step(
                self._graph.add("ext", self._source_title(statement), statement.line)
            )

    def _step(self, node: _Node) -> None:
        for source, label in self._tails:
            self._graph.link(source, label, node)
        self._tails = [(node, "then")]

    def _expression_statement(self, value: m.Expr) -> None:
        if isinstance(value, m.Literal):
            return
        if isinstance(value, m.Call):
            self._call(value, exec_candidate=True, out_names=())
        elif isinstance(value, m.Await) and isinstance(value.value, m.Call):
            self._call(value.value, exec_candidate=True, out_names=(), awaited=True)
        elif isinstance(value, m.Yield):
            self._yield(value, discard=True)
        else:
            self._expr(value)

    def _assign(self, statement: m.Assign, *, exec_candidate: bool) -> None:
        if statement.value is None:
            return
        targets = statement.targets
        names = _assigned_names(targets[0]) if len(targets) == 1 else None
        call, awaited = _unwrap_call(statement.value)
        if (
            call is not None
            and names is not None
            and len(names) > 1
            and isinstance(targets[0], m.Sequence)
        ):
            outputs = self._call(
                call, exec_candidate=exec_candidate, out_names=names, awaited=awaited
            )
            for target, output in zip(_flat_targets(targets[0]), outputs):
                self._bind(target, output, statement.line)
            return
        out_name = names[0] if names is not None and len(names) == 1 else ""
        value = self._expr(
            statement.value, exec_candidate=exec_candidate, out_name=out_name
        )
        if statement.annotation is not None:
            value = replace(
                value,
                type=self._annotation_type(statement.annotation),
                annotation=(statement.annotation, self._module),
            )
        for target in targets:
            self._bind(target, value, statement.line)

    def _bind(self, target: m.Expr, value: _Value, line: int) -> None:
        if isinstance(target, m.Name):
            self._bind_name(target.id, value, line)
        elif isinstance(target, m.Spread):
            self._bind(target.value, value, line)
        elif isinstance(target, m.Sequence):
            for element, part in zip(
                target.elements, self._unpack(value, target, line)
            ):
                self._bind(element, part, line)
        elif isinstance(target, m.Member):
            node = self._graph.add("set", f"Set {self._text(target)}", line)
            self._graph.connect(node, _pin_name(target.value), self._expr(target.value))
            self._graph.connect(node, "value", value)
            self._step(node)
        elif isinstance(target, m.Subscript):
            container = self._expr(target.value)
            key = self._expr(target.index)
            node = self._graph.add("set", f"Set {self._text(target)}", line)
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

    def _unpack(self, value: _Value, target: m.Sequence, line: int) -> list[_Value]:
        node = self._graph.add("op", "Unpack", line)
        self._graph.connect(node, "value", value)
        return [
            self._graph.output(node, self._target_label(element), UNKNOWN)
            for element in target.elements
        ]

    def _augmented_assign(self, statement: m.AugAssign) -> None:
        symbol = statement.op
        target = statement.target
        value = self._expr(statement.value)
        if isinstance(target, m.Name):
            current = self._name_value(target.id, statement.line)
            node = self._graph.add("set", f"Set {target.id} {symbol}=", statement.line)
            self._graph.connect(node, target.id, current)
            self._graph.connect(node, "value", value)
            self._step(node)
            self._env[target.id] = self._graph.output(
                node, target.id, current.type, current.annotation
            )
            return
        base = target.value if isinstance(target, (m.Member, m.Subscript)) else target
        container = self._expr(base)
        key = self._expr(target.index) if isinstance(target, m.Subscript) else None
        node = self._graph.add(
            "set", f"Set {self._text(target)} {symbol}=", statement.line
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

    def _if(self, statement: m.If) -> None:
        if self._is_data_block([statement]) and not _contains_return([statement]):
            self._merge_if(statement)
        else:
            self._branch_if(statement)

    def _merge_if(self, statement: m.If) -> None:
        condition = self._expr(statement.test)
        saved = dict(self._env)
        self._data_block(statement.body)
        true_env = self._env
        self._env = dict(saved)
        self._data_block(statement.orelse)
        self._env = self._merge(condition, true_env, self._env, statement.line)

    def _branch_if(self, statement: m.If) -> None:
        condition: _Value | None = None
        if self._folds(statement.test, named=True):
            node = self._inline_condition(
                statement.test,
                lambda: self._graph.add(
                    "branch", "Branch", statement.line, exec_outs=["True", "False"]
                ),
            )
        else:
            condition = self._expr(statement.test, exec_candidate=True)
            node = self._graph.add(
                "branch", "Branch", statement.line, exec_outs=["True", "False"]
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
            self._env = self._merge(condition, true_env, false_env, statement.line)

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
        self, statements: Sequence[m.Stmt], *, function_level: bool
    ) -> bool:
        if not _contains_return(statements[:1]) or not self._is_data_block(statements):
            return False
        return function_level or _always_terminates(statements)

    def _return_region(self, statements: Sequence[m.Stmt]) -> None:
        outcome = self._data_block(statements)
        value = (
            outcome.value
            if outcome.terminated and outcome.value is not None
            else self._none_literal()
        )
        self._emit_return(value, statements[-1].line)

    def _data_block(self, statements: Sequence[m.Stmt]) -> _Outcome:
        for index, statement in enumerate(statements):
            if isinstance(statement, m.Return):
                value = (
                    self._expr(statement.value)
                    if statement.value is not None
                    else self._none_literal()
                )
                return _Outcome(value, True)
            if isinstance(statement, m.If):
                outcome = self._data_if(statement, statements[index + 1 :])
                if outcome is not None:
                    return outcome
            elif isinstance(statement, m.Assign):
                self._assign(statement, exec_candidate=False)
        return _Outcome(None, False)

    def _data_if(self, statement: m.If, rest: Sequence[m.Stmt]) -> _Outcome | None:
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
                    self._returned(when_true),
                    self._returned(when_false),
                    statement.line,
                ),
                True,
            )
        if not when_true.terminated and not when_false.terminated:
            if isinstance(condition, _Folded):
                condition = self._expression_node(condition, "Check", statement.line)
            self._env = self._merge(condition, true_env, self._env, statement.line)
            return None
        if when_false.terminated:
            self._env = true_env
        continuation = self._data_block(rest)
        later = self._returned(continuation)
        if when_true.terminated:
            return _Outcome(
                self._select_on(
                    condition, self._returned(when_true), later, statement.line
                ),
                True,
            )
        return _Outcome(
            self._select_on(
                condition, later, self._returned(when_false), statement.line
            ),
            True,
        )

    def _is_data_block(self, statements: Sequence[m.Stmt]) -> bool:
        return all(self._is_data_statement(statement) for statement in statements)

    def _is_data_statement(self, statement: m.Stmt) -> bool:
        if isinstance(statement, m.Pass) or (
            isinstance(statement, m.ExprStmt) and isinstance(statement.value, m.Literal)
        ):
            return True
        if isinstance(statement, m.Return):
            return statement.value is None or not _suspends(statement.value)
        if isinstance(statement, m.Assign):
            names = [
                name
                for target in statement.targets
                for name in (_assigned_names(target) or ["."])
            ]
            if any(
                name.startswith("*")
                or name == "."
                or name in self._carried
                or name in self._declared_globals
                for name in names
            ):
                return False
            value = statement.value
            return value is None or (
                not _suspends(value) and not self._is_effectful_call(value)
            )
        if isinstance(statement, m.If):
            return (
                not _suspends(statement.test)
                and self._is_data_block(statement.body)
                and self._is_data_block(statement.orelse)
            )
        return False

    def _is_effectful_call(self, value: m.Expr) -> bool:
        return isinstance(value, m.Call) and not self._call_is_pure(value)

    def _for(self, statement: m.For) -> None:
        items = self._expr(statement.iter, exec_candidate=True)
        targets = _flat_targets(statement.target)
        title = ", ".join(self._target_label(target) for target in targets)
        node = self._graph.add(
            "loop",
            f"For each {title}",
            statement.line,
            exec_outs=["Loop body", "Completed"],
            note="async for" if statement.is_async else None,
        )
        self._graph.connect(node, "items", items)
        element = self._element_type(items) if len(targets) == 1 else UNKNOWN
        outputs = [
            self._graph.output(node, self._target_label(target), element)
            for target in targets
        ]
        self._step(node)
        for target, output in zip(targets, outputs):
            if isinstance(target, m.Name):
                self._env[target.id] = output
            else:
                self._bind(target, output, statement.line)
        self._loop_body(node, statement.body, statement.orelse)

    def _while(self, statement: m.While) -> None:
        if self._folds(statement.test, named=True):
            node = self._inline_condition(
                statement.test,
                lambda: self._graph.add(
                    "loop",
                    "While",
                    statement.line,
                    exec_outs=["Loop body", "Completed"],
                ),
            )
        else:
            condition = self._expr(statement.test)
            node = self._graph.add(
                "loop",
                f"While {self._text(statement.test)}",
                statement.line,
                exec_outs=["Loop body", "Completed"],
            )
            self._graph.connect(node, "condition", condition, _BOOL)
        self._step(node)
        self._loop_body(node, statement.body, statement.orelse)

    def _loop_body(
        self, node: _Node, body: Sequence[m.Stmt], orelse: Sequence[m.Stmt]
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

    def _with(self, statement: m.With) -> None:
        contexts = [self._expr(item.context) for item in statement.items]
        title = ", ".join(self._text(item.context) for item in statement.items)
        node = self._graph.add(
            "ext",
            f"With {title}",
            statement.line,
            note="async with" if statement.is_async else None,
        )
        bindings: list[tuple[m.Expr, _Value]] = []
        for item, context in zip(statement.items, contexts):
            self._graph.connect(node, "context", context)
            if item.target is not None:
                entered = context.type if isinstance(item.target, m.Name) else UNKNOWN
                bindings.append(
                    (
                        item.target,
                        self._graph.output(
                            node, self._target_label(item.target), entered
                        ),
                    )
                )
        self._step(node)
        for target, value in bindings:
            self._bind(target, value, statement.line)
        self._run_block(statement.body, function_level=False)

    def _try(self, statement: m.Try) -> None:
        labels = [
            "Try",
            *(
                (
                    f"{self._profile.handler_word} {self._text(handler.type)}"
                    if handler.type is not None
                    else self._profile.handler_word
                )
                for handler in statement.handlers
            ),
        ]
        node = self._graph.add(
            "branch",
            "Try",
            statement.line,
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

    def _exception_type(self, annotation: m.Expr | None) -> PinType:
        dotted = m.dotted_name(annotation) if annotation is not None else None
        if annotation is not None and dotted is not None:
            return self._annotation_type(
                m.TypeName(
                    annotation.line,
                    annotation.end_line,
                    dotted,
                    origin=annotation.origin,
                )
            )
        return PinType(self._profile.default_exception, "object")

    def _raise(self, statement: m.Raise) -> None:
        exception = statement.exc
        if exception is None:
            node = self._graph.add("raise", "Re-raise", statement.line)
        elif isinstance(exception, m.Call) and self._raises_class(exception):
            callee = self._resolve_callee(exception)
            arguments = self._arguments(exception, callee, first_fallback="message")
            name = _short_name(callee.title.removeprefix("Make "))
            node = self._graph.add(
                "raise",
                f"Raise {name}",
                statement.line,
                target=callee.target,
                external=callee.external,
            )
            self._connect_arguments(node, arguments)
        else:
            value = self._expr(exception)
            title = (
                f"Raise {_short_name(self._text(exception))}"
                if value.literal is not None
                else "Raise"
            )
            node = self._graph.add(
                "raise",
                title,
                statement.line,
                target=value.type.ref if value.literal is not None else None,
            )
            if value.literal is None:
                self._graph.connect(node, "error", value)
        if statement.cause is not None:
            self._graph.connect(node, "cause", self._expr(statement.cause))
        self._step(node)
        self._tails = []

    def _raises_class(self, call: m.Call) -> bool:
        name = m.dotted_name(call.func)
        if name is None or self._is_local(name.split(".")[0]):
            return False
        last = name.rsplit(".", 1)[-1]
        return last[:1].isupper()

    def _match(self, statement: m.Match) -> None:
        subject = self._expr(statement.subject, exec_candidate=True)
        labels = [
            _shorten(
                self._language.case_label(case.pattern)
                + (f" if {self._text(case.guard)}" if case.guard else ""),
                _LABEL_LIMIT,
            )
            for case in statement.cases
        ]
        exhaustive = any(
            case.pattern.catch_all and case.guard is None for case in statement.cases
        )
        node = self._graph.add(
            "branch",
            f"{self._profile.match_title} {self._text(statement.subject)}",
            statement.line,
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
            for name in case.pattern.captures:
                self._env[name] = self._graph.output(node, name, UNKNOWN)
            if case.guard is not None:
                self._expr(case.guard)
            self._tails = [(node, label)]
            self._run_block(case.body, function_level=False)
            tails = tails + self._tails
            env.update(self._env)
        self._tails, self._env = tails, env

    def _assert(self, statement: m.Assert) -> None:
        condition = self._expr(statement.test)
        node = self._graph.add("raise", "Assert", statement.line)
        self._graph.connect(node, "condition", condition, _BOOL)
        if statement.msg is not None:
            self._graph.connect(node, "message", self._expr(statement.msg))
        self._step(node)

    def _delete(self, statement: m.Delete) -> None:
        for target in statement.targets:
            if isinstance(target, m.Name):
                self._env.pop(target.id, None)
                continue
            base = (
                target.value if isinstance(target, (m.Member, m.Subscript)) else target
            )
            container = self._expr(base)
            key = self._expr(target.index) if isinstance(target, m.Subscript) else None
            node = self._graph.add(
                "set", f"Delete {self._text(target)}", statement.line
            )
            self._graph.connect(node, _pin_name(base), container)
            if key is not None:
                self._graph.connect(node, "key", key)
            self._step(node)

    def _yield(self, expression: m.Yield, *, discard: bool) -> _Value:
        value = self._expr(expression.value) if expression.value is not None else None
        node = self._graph.add(
            "return",
            "Yield from" if expression.delegate else "Yield",
            expression.line,
        )
        if value is not None:
            self._graph.connect(node, "value", value)
        self._step(node)
        if discard:
            return self._none_literal()
        return self._graph.output(node, "sent", UNKNOWN)

    def _expr(
        self, expression: m.Expr, *, exec_candidate: bool = False, out_name: str = ""
    ) -> _Value:
        literal = self._literal(expression)
        if literal is not None:
            return literal
        if isinstance(expression, m.Name):
            return self._name_value(expression.id, expression.line)
        if self._folds(expression, named=bool(out_name)):
            return self._expression(expression, out_name)
        if isinstance(expression, m.Member):
            return self._attribute(expression)
        if isinstance(expression, m.Call):
            if self._is_super_call(expression) and not self._is_local(
                self._profile.super_name
            ):
                return self._super_value()
            return self._call(
                expression, exec_candidate=exec_candidate, out_names=(out_name,)
            )[0]
        if isinstance(expression, m.Await):
            return self._await(
                expression, exec_candidate=exec_candidate, out_name=out_name
            )
        if isinstance(expression, m.Logical):
            return self._bool_op(expression)
        if isinstance(expression, m.Binary):
            return self._binary(expression)
        if isinstance(expression, m.Unary):
            return self._unary(expression)
        if isinstance(expression, m.Compare):
            return self._compare(expression)
        if isinstance(expression, m.Conditional):
            condition = self._expr(expression.test)
            return self._select(
                condition,
                self._expr(expression.body),
                self._expr(expression.orelse),
                expression.line,
            )
        if isinstance(expression, m.Subscript):
            return self._subscript(expression)
        if isinstance(expression, m.Template):
            return self._format_text(expression)
        if isinstance(expression, (m.Sequence, m.Mapping)):
            return self._collection(expression)
        if isinstance(expression, m.Comprehension):
            title, label, cat = self._profile.comprehensions[expression.kind]
            return self._opaque(
                expression, title, PinType(label, cat), code=self._text(expression)
            )
        if isinstance(expression, m.Function):
            return self._function_value(expression)
        if isinstance(expression, m.AssignExpr):
            value = self._expr(expression.value, out_name=expression.target.id)
            self._env[expression.target.id] = value
            return value
        if isinstance(expression, m.Spread):
            return self._expr(expression.value)
        if isinstance(expression, m.Yield):
            return self._yield(expression, discard=False)
        if isinstance(expression, m.Interpolation):
            return self._expr(expression.value)
        return self._opaque(expression, self._text(expression), UNKNOWN, code=None)

    def _function_value(self, expression: m.Function) -> _Value:
        return self._opaque(
            expression,
            expression.name or self._profile.function_title,
            _CALLABLE,
            code=self._text(expression),
        )

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
            head in self._profile.builtin_names
            and head not in self._module.imports
            and head not in self._module.top_level
            and head not in self._module_variables
        ):
            return _Value(
                (
                    PinType(head, "class")
                    if head in self._profile.builtin_classes
                    else _CALLABLE
                ),
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
            else self._literal_type_of(value)
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

    def _attribute(self, expression: m.Member) -> _Value:
        attributes, base = _split_attribute(expression)
        if (
            isinstance(base, m.Name)
            and not self._is_local(base.id)
            and base.id not in self._module_variables
        ):
            return self._global_value(
                f"{base.id}.{'.'.join(attributes)}", expression.line
            )
        current = self._expr(base)
        prefix = base.id if isinstance(base, m.Name) else None
        pin_name = _pin_name(base)
        index = 0
        while index < len(attributes):
            end = self._group_end(prefix, attributes, index)
            name = ".".join(attributes[index : end + 1])
            pin_type, annotation = self._attribute_chain_type(
                current, attributes[index : end + 1]
            )
            current = self._break_read(
                current, pin_name, name, pin_type, annotation, expression.line
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
        annotation: tuple[m.TypeExpr, ParsedModule] | None,
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
    ) -> tuple[PinType, tuple[m.TypeExpr, ParsedModule] | None]:
        current = base.type
        annotation: tuple[m.TypeExpr, ParsedModule] | None = None
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
        if isinstance(annotation, m.TypeName) and annotation.args:
            names = module.language.profile.types
            base = annotation.dotted.rsplit(".", 1)[-1]
            if (
                base in names.sequences
                or base in names.mappings
                or base in names.tuples
            ):
                return self._resolver(module).annotation(annotation.args[0])
        return UNKNOWN

    def _item_type(self, container: _Value, key: m.Expr) -> PinType:
        if container.annotation is None:
            return UNKNOWN
        annotation, module = container.annotation
        if not isinstance(annotation, m.TypeName) or not annotation.args:
            return UNKNOWN
        names = module.language.profile.types
        base = annotation.dotted.rsplit(".", 1)[-1]
        arguments = annotation.args
        if base in names.mappings and len(arguments) == 2:
            return self._resolver(module).annotation(arguments[1])
        if base in names.sequences and not isinstance(key, m.Slice):
            return self._resolver(module).annotation(arguments[0])
        if (
            base in names.tuples
            and isinstance(key, m.Literal)
            and isinstance(key.value, int)
            and -len(arguments) <= key.value < len(arguments)
        ):
            chosen = (
                arguments[0]
                if len(arguments) == 2 and isinstance(arguments[1], m.TypeLiteral)
                else arguments[key.value]
            )
            return self._resolver(module).annotation(chosen)
        return UNKNOWN

    def _call(
        self,
        call: m.Call,
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
            call.line,
            target=callee.target,
            external=callee.external,
            note=callee.note,
        )
        if awaited:
            node.notes.append("awaits")
        if callee.receiver is not None:
            self._graph.connect(
                node,
                callee.receiver_name or self._profile.instance_receiver,
                callee.receiver,
            )
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
        self, call: m.Call, callee: _Callee, first_fallback: str | None = None
    ) -> list[_Argument]:
        arguments: list[_Argument] = []
        for index, argument in enumerate(call.args):
            if isinstance(argument, m.Spread):
                name = (
                    f"{self._profile.spread_prefix}{_pin_name(argument.value, 'args')}"
                )
            elif index < len(callee.parameters):
                name = callee.parameters[index]
            elif callee.vararg is not None:
                name = f"{self._profile.spread_prefix}{callee.vararg}"
            elif index == 0 and first_fallback is not None:
                name = first_fallback
            else:
                name = _argument_name(argument, index)
            arguments.append(self._argument(name, argument, callee))
        for keyword in call.keywords:
            name = (
                keyword.arg
                if keyword.arg is not None
                else f"{self._profile.mapping_spread_prefix}"
                f"{_pin_name(keyword.value, 'kwargs')}"
            )
            arguments.append(self._argument(name, keyword.value, callee))
        return arguments

    def _argument(self, name: str, expression: m.Expr, callee: _Callee) -> _Argument:
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

    def _resolve_callee(self, call: m.Call) -> _Callee:
        function = call.func
        if isinstance(function, m.Name):
            if function.id in self._local_functions:
                return _Callee("ext", function.id, pure=False, note="Local function")
            if self._is_local(function.id):
                return self._local_callee(
                    function.id, self._name_value(function.id, call.line)
                )
            return self._global_callee(function.id, call.line)
        if isinstance(function, m.Member):
            dotted = m.dotted_name(function)
            if dotted is not None and not self._is_local(dotted.split(".")[0]):
                return self._global_callee(dotted, call.line)
            return self._method_callee(function, self._expr(function.value))
        return _Callee(
            "ext",
            self._text(function),
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

    def _call_is_pure(self, call: m.Call) -> bool:
        function = call.func
        if isinstance(function, m.Name):
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
        if isinstance(function, m.Member):
            dotted = m.dotted_name(function)
            if dotted is not None and not self._is_local(dotted.split(".")[0]):
                return self._global_is_pure(dotted)
            return function.attr in self._profile.pure_methods
        return False

    def _global_is_pure(self, dotted: str) -> bool:
        head, _, rest = dotted.partition(".")
        if head in self._module_variables and rest:
            return dotted.rsplit(".", 1)[-1] in self._profile.pure_methods
        resolved = self._workspace.resolve(self._module, dotted)
        if isinstance(resolved, SymbolRef):
            return self._workspace.parsed_class(resolved) is not None and _same_last(
                dotted, resolved.sym
            )
        if isinstance(resolved, ExternalRef):
            return _external_is_pure(self._profile, _external_name(resolved))
        if (
            resolved is None
            and dotted in self._profile.builtin_names
            and dotted not in self._module.imports
        ):
            return dotted in self._profile.pure_builtins or dotted[:1].isupper()
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
                self._receiver_title(dotted),
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
        if resolved is None and dotted in self._profile.builtin_names:
            return _Callee(
                "ext",
                dotted,
                pure=pure,
                parameters=self._profile.builtin_parameters.get(dotted, ()),
                result=self._profile_type(self._profile.builtin_results.get(dotted)),
            )
        return _Callee("ext", dotted, pure=pure)

    def _make_callee(self, ref: SymbolRef) -> _Callee:
        name = ref.sym.rsplit(".", 1)[-1]
        result = self._types.class_type(ref)
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
                    isinstance(statement, m.Assign)
                    and statement.annotation is not None
                    and isinstance(statement.targets[0], m.Name)
                    and not _is_class_variable(module, statement.annotation)
                ):
                    fields[statement.targets[0].id] = self._resolver(module).annotation(
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
        is_method = (
            function.class_qualname is not None and function.node.binding != "static"
        )
        skip_first = is_method and (bound or function.node.binding == "class")
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
        resolver = self._resolver(module)
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

    def _method_callee(self, function: m.Member, receiver: _Value) -> _Callee:
        return self._method_callee_named(
            self._receiver_title(self._text(function), function.value),
            function.attr,
            receiver,
            pure=function.attr in self._profile.pure_methods,
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
            if method in self._profile.same_type_methods and receiver.type.cat != "any"
            else self._profile_type(self._profile.method_results.get(method))
        )
        return _Callee("method", title, pure=pure, result=result, receiver=receiver)

    def _await(
        self, expression: m.Await, *, exec_candidate: bool, out_name: str
    ) -> _Value:
        if isinstance(expression.value, m.Call):
            return self._call(
                expression.value,
                exec_candidate=exec_candidate,
                out_names=(out_name,),
                awaited=True,
            )[0]
        value = self._expr(expression.value)
        node = self._graph.add("ext", "await", expression.line, note="awaits")
        self._graph.connect(node, "awaitable", value)
        if exec_candidate:
            self._step(node)
        return self._graph.output(node, out_name, UNKNOWN)

    def _folds(self, expression: m.Expr, *, named: bool) -> bool:
        if isinstance(expression, m.Name) or _is_literal_expression(expression):
            return False
        if self._folded_parts(expression) is None:
            return False
        computations, operations = self._fold_counts(expression)
        return computations >= 2 or (named and operations >= 1)

    def _expression(self, expression: m.Expr, name: str) -> _Value:
        return self._expression_node(self._fold(expression), name, expression.line)

    def _expression_node(self, folded: _Folded, name: str, line: int) -> _Value:
        title = name or ("Check" if folded.result.cat == "bool" else "Calculate")
        node = self._graph.add("expr", title, line)
        self._write_expression(node, folded)
        return self._graph.output(node, "", folded.result)

    def _inline_condition(
        self, expression: m.Expr, create: Callable[[], _Node]
    ) -> _Node:
        folded = self._fold(expression)
        node = create()
        self._write_expression(node, folded)
        return node

    def _write_expression(self, node: _Node, folded: _Folded) -> None:
        node.expression = folded.lines
        for pin, value in folded.inputs:
            self._graph.connect(node, pin, value)

    def _fold(self, expression: m.Expr) -> _Folded:
        inputs: dict[str, _Value] = {}
        values: dict[int, _Value] = {}
        types: dict[int, PinType] = {}
        leaves: dict[m.Node, str] = {}
        self._fold_walk(expression, inputs, values, types, leaves)
        return _Folded(
            list(inputs.items()),
            types.get(id(expression), UNKNOWN),
            self._printer.lines(expression, leaves, _EXPRESSION_WIDTH),
        )

    def _fold_walk(
        self,
        expression: m.Expr,
        inputs: dict[str, _Value],
        values: dict[int, _Value],
        types: dict[int, PinType],
        leaves: dict[m.Node, str],
    ) -> None:
        literal = self._literal(expression)
        if literal is not None:
            types[id(expression)] = literal.type
            return
        if isinstance(expression, m.Name):
            if self._is_local(expression.id):
                value = inputs.get(expression.id) or self._name_value(
                    expression.id, expression.line
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
                    _shorten(self._text(expression), _INPUT_NAME_LIMIT), set(inputs)
                )
                inputs[name] = value
                leaves[expression] = name
            values[id(expression)] = value
            types[id(expression)] = value.type
            return
        for part in parts:
            self._fold_walk(part, inputs, values, types, leaves)
        types[id(expression)] = self._folded_type(expression, types, values)

    def _on_project_object(self, expression: m.Expr) -> bool:
        root = expression
        while isinstance(root, (m.Member, m.Subscript)):
            root = root.value
        if not isinstance(root, m.Name) or not self._is_local(root.id):
            return False
        binding = self._env.get(root.id)
        return isinstance(binding, _Value) and binding.type.ref is not None

    def _folded_parts(self, expression: m.Expr) -> list[m.Expr] | None:
        if isinstance(expression, m.Logical):
            return list(expression.values)
        if isinstance(expression, m.Binary):
            return [expression.left, expression.right]
        if isinstance(expression, m.Unary):
            return [expression.operand]
        if isinstance(expression, m.Compare):
            return [expression.left, *expression.comparators]
        if isinstance(expression, m.Conditional):
            return [expression.test, expression.body, expression.orelse]
        if isinstance(expression, m.Member):
            dotted = m.dotted_name(expression)
            if dotted is not None and not self._is_local(dotted.split(".")[0]):
                return []
            if self._on_project_object(expression):
                return None
            return [expression.value]
        if isinstance(expression, m.Subscript):
            return [expression.value, expression.index]
        if isinstance(expression, m.Slice):
            return [
                part
                for part in (expression.lower, expression.upper, expression.step)
                if part is not None
            ]
        if isinstance(expression, m.Sequence):
            if any(isinstance(element, m.Spread) for element in expression.elements):
                return None
            return list(expression.elements)
        if isinstance(expression, m.Call) and self._folds_call(expression):
            return [
                *self._method_receiver(expression.func),
                *expression.args,
                *(keyword.value for keyword in expression.keywords),
            ]
        return None

    def _method_receiver(self, function: m.Expr) -> list[m.Expr]:
        if not isinstance(function, m.Member):
            return []
        dotted = m.dotted_name(function)
        if dotted is not None and not self._is_local(dotted.split(".")[0]):
            return []
        return [function.value]

    def _folds_call(self, call: m.Call) -> bool:
        if any(isinstance(argument, m.Spread) for argument in call.args) or any(
            keyword.arg is None for keyword in call.keywords
        ):
            return False
        function = call.func
        if isinstance(function, m.Name):
            return not self._is_local(function.id) and self._global_folds(function.id)
        if isinstance(function, m.Member):
            dotted = m.dotted_name(function)
            if dotted is not None and not self._is_local(dotted.split(".")[0]):
                return self._global_folds(dotted)
            return (
                function.attr in self._profile.pure_methods
                and not self._on_project_object(function.value)
            )
        return False

    def _global_folds(self, dotted: str) -> bool:
        if dotted.rsplit(".", 1)[-1][:1].isupper():
            return False
        if isinstance(self._workspace.resolve(self._module, dotted), SymbolRef):
            return False
        return self._global_is_pure(dotted)

    def _fold_counts(self, expression: m.Expr) -> tuple[int, int]:
        if isinstance(expression, m.Name) or _is_literal_expression(expression):
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
        expression: m.Expr,
        types: dict[int, PinType],
        values: dict[int, _Value],
    ) -> PinType:
        def of(part: m.Expr) -> PinType:
            return types.get(id(part), UNKNOWN)

        if isinstance(expression, m.Compare):
            return _BOOL
        if isinstance(expression, m.Logical):
            parts = [of(value) for value in expression.values]
            return _BOOL if all(part.cat == "bool" for part in parts) else parts[0]
        if isinstance(expression, m.Unary):
            return _BOOL if expression.op == "not" else of(expression.operand)
        if isinstance(expression, m.Binary):
            left, right = of(expression.left), of(expression.right)
            if left.cat != "any" and left.cat == right.cat:
                return left
            if {left.cat, right.cat} == {"int", "float"}:
                return _FLOAT
            return left if left.cat == "str" else UNKNOWN
        if isinstance(expression, m.Conditional):
            body, orelse = of(expression.body), of(expression.orelse)
            return body if body.cat == orelse.cat else UNKNOWN
        if isinstance(expression, m.Call):
            return self._folded_call_type(expression, types)
        if isinstance(expression, m.Subscript):
            container = values.get(id(expression.value))
            return (
                self._item_type(container, expression.index)
                if container is not None
                else UNKNOWN
            )
        return UNKNOWN

    def _folded_call_type(self, call: m.Call, types: dict[int, PinType]) -> PinType:
        dotted = m.dotted_name(call.func) or ""
        if dotted in self._profile.builtin_results:
            return self._profile_type(self._profile.builtin_results[dotted])
        resolved = self._workspace.resolve(self._module, dotted) if dotted else None
        if (
            isinstance(resolved, ExternalRef)
            and _external_name(resolved).split(".")[0] in self._profile.numeric_modules
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

    def _bool_op(self, expression: m.Logical) -> _Value:
        values = [self._expr(value) for value in expression.values]
        result = (
            _BOOL
            if all(value.type.cat == "bool" for value in values)
            else values[0].type
        )
        title = _LOGICAL.get(expression.op, expression.op)
        return self._operation(
            title,
            expression.line,
            [(_letter(index), value) for index, value in enumerate(values)],
            result,
        )

    def _binary(self, expression: m.Binary) -> _Value:
        left = self._expr(expression.left)
        right = self._expr(expression.right)
        result = (
            left.type
            if left.type.cat != "any" and left.type.cat == right.type.cat
            else (left.type if left.type.cat == "str" else UNKNOWN)
        )
        return self._operation(
            expression.op,
            expression.line,
            [("a", left), ("b", right)],
            result,
        )

    def _unary(self, expression: m.Unary) -> _Value:
        operand = self._expr(expression.operand)
        result = _BOOL if expression.op == "not" else operand.type
        return self._operation(
            _UNARY.get(expression.op, expression.op),
            expression.line,
            [("value", operand)],
            result,
        )

    def _compare(self, expression: m.Compare) -> _Value:
        if (
            len(expression.ops) == 1
            and expression.ops[0] in ("is", "is not")
            and _is_none(expression.comparators[0])
        ):
            title = "is None" if expression.ops[0] == "is" else "is not None"
            return self._operation(
                title,
                expression.line,
                [("value", self._expr(expression.left))],
                _BOOL,
            )
        operands = [
            self._expr(expression.left),
            *(self._expr(comparator) for comparator in expression.comparators),
        ]
        symbols = [_COMPARISONS.get(op, op) for op in expression.ops]
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
            expression.line,
            [(_letter(index), value) for index, value in enumerate(operands)],
            _BOOL,
        )

    def _subscript(self, expression: m.Subscript) -> _Value:
        container = self._expr(expression.value)
        container_name = _pin_name(expression.value)
        result = self._item_type(container, expression.index)
        key = expression.index
        if isinstance(key, m.Slice):
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
                f"[{self._text(key)}]",
                expression.line,
                inputs,
                container.type if result is UNKNOWN else result,
            )
        key_value = self._expr(key)
        if key_value.literal is not None and len(key_value.literal) <= 20:
            return self._operation(
                f"[{key_value.literal}]",
                expression.line,
                [(container_name, container)],
                result,
            )
        return self._operation(
            "[ ]",
            expression.line,
            [(container_name, container), ("key", key_value)],
            result,
        )

    def _format_text(self, expression: m.Template) -> _Value:
        pieces: dict[str, _Value] = {}
        for part in expression.parts:
            if isinstance(part, m.Interpolation):
                text = _shorten(self._text(part.value), 30)
                if text not in pieces:
                    pieces[text] = self._expr(part.value)
        node = self._graph.add(
            "make", "Format text", expression.line, code=self._text(expression)
        )
        for name, value in pieces.items():
            self._graph.connect(node, name, value)
        return self._graph.output(node, "", _STR)

    def _collection(self, expression: m.Sequence | m.Mapping) -> _Value:
        if isinstance(expression, m.Mapping):
            return self._dictionary(expression)
        kind_name, cat = self._profile.sequence_kinds.get(
            expression.kind, (expression.kind, "list")
        )
        result = PinType(kind_name, cat)
        spread = self._profile.spread_prefix
        inputs: list[tuple[str, _Value]] = []
        for index, element in enumerate(expression.elements):
            if isinstance(element, m.Spread):
                inputs.append(
                    (
                        f"{spread}{_pin_name(element.value, 'items')}",
                        self._expr(element.value),
                    )
                )
            else:
                inputs.append((_element_name(element, index), self._expr(element)))
        node = self._graph.add("make", f"Make {kind_name}", expression.line)
        for name, value in inputs:
            self._graph.connect(node, name, value)
        return self._graph.output(node, kind_name, result)

    def _dictionary(self, expression: m.Mapping) -> _Value:
        inputs: list[tuple[str, _Value]] = []
        spread = self._profile.mapping_spread_prefix
        for index, (key, value) in enumerate(zip(expression.keys, expression.values)):
            if key is None:
                inputs.append(
                    (f"{spread}{_pin_name(value, 'mapping')}", self._expr(value))
                )
            elif isinstance(key, m.Literal) and isinstance(key.value, str):
                inputs.append((key.value or '""', self._expr(value)))
            else:
                inputs.append((f"key {index + 1}", self._expr(key)))
                inputs.append((f"value {index + 1}", self._expr(value)))
        label, cat = self._profile.mapping_kind
        node = self._graph.add("make", f"Make {label}", expression.line)
        for name, entry in inputs:
            self._graph.connect(node, name, entry)
        return self._graph.output(node, label, PinType(label, cat))

    def _opaque(
        self, expression: m.Expr, title: str, result: PinType, *, code: str | None
    ) -> _Value:
        inputs = [
            (name, self._name_value(name, expression.line))
            for name in _free_names(expression)
            if name in self._env or name in self._module_variables
        ]
        node = self._graph.add("ext", title, expression.line, code=code)
        for name, value in inputs:
            self._graph.connect(node, name, value)
        return self._graph.output(node, "", result)

    def _annotation_type(self, annotation: m.TypeExpr | None) -> PinType:
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

    def _text(self, node: m.Node) -> str:
        return self._language.text(node)

    def _native_labels(self, graph: dict[str, Any]) -> None:
        labels = self._profile.literal_labels
        if not labels:
            return
        for node in graph.get("nodes", []):
            for pin in [*node.get("ins", []), *node.get("outs", [])]:
                kind = pin.get("type")
                if isinstance(kind, dict) and kind.get("label") in labels:
                    kind["label"] = labels[kind["label"]]

    def _profile_type(self, entry: tuple[str, str] | None) -> PinType:
        return PinType(*entry) if entry is not None else UNKNOWN

    def _none_type(self) -> PinType:
        return PinType(self._profile.none_text, "none")

    def _none_literal(self) -> _Value:
        return _Value(self._none_type(), literal=self._profile.none_text)

    def _returned(self, outcome: _Outcome) -> _Value:
        return (
            outcome.value
            if outcome.terminated and outcome.value is not None
            else self._none_literal()
        )

    def _literal(self, expression: m.Expr) -> _Value | None:
        if not _is_literal_expression(expression):
            return None
        if isinstance(expression, m.Literal):
            if isinstance(expression.value, str):
                return _Value(
                    _STR,
                    literal=_shorten(
                        json.dumps(expression.value, ensure_ascii=False),
                        _LITERAL_LIMIT,
                    ),
                )
            if expression.value is Ellipsis:
                return _Value(UNKNOWN, literal="...")
            literal = _shorten(self._text(expression), _LITERAL_LIMIT)
            if expression.value is None:
                return _Value(self._none_type(), literal=literal)
            return _Value(literal_type(expression.value), literal=literal)
        text = self._text(expression)
        if len(text) > _LITERAL_LIMIT:
            return None
        if isinstance(expression, m.Unary) and isinstance(
            expression.operand, m.Literal
        ):
            return _Value(literal_type(expression.operand.value), literal=text)
        if isinstance(expression, m.Sequence):
            entry = self._profile.sequence_kinds.get(expression.kind)
            return _Value(self._profile_type(entry), literal=text)
        if isinstance(expression, m.Mapping):
            return _Value(PinType(*self._profile.mapping_kind), literal=text)
        return _Value(UNKNOWN, literal=text)

    def _literal_type_of(self, value: m.Expr | None) -> PinType:
        literal = self._literal(value) if value is not None else None
        return literal.type if literal is not None else UNKNOWN

    def _is_super_call(self, expression: m.Expr) -> bool:
        if isinstance(expression, m.Call):
            expression = expression.func
        return (
            isinstance(expression, m.Name) and expression.id == self._profile.super_name
        )

    def _receiver_title(self, text: str, receiver: m.Expr | None = None) -> str:
        if receiver is not None and self._is_super_call(receiver):
            call = "()" if isinstance(receiver, m.Call) else ""
            return f"{self._profile.super_name}{call}.{text.rsplit('.', 1)[-1]}"
        if receiver is not None and m.dotted_name(receiver) is None:
            return text.rsplit(".", 1)[-1]
        parts = text.split(".")
        return ".".join(parts[-2:])

    def _source_title(self, statement: m.Stmt) -> str:
        text = self._text(statement)
        return text.splitlines()[0] if text else type(statement).__name__

    def _target_label(self, target: m.Expr) -> str:
        if isinstance(target, m.Name):
            return target.id
        if isinstance(target, m.Spread):
            return f"{self._profile.spread_prefix}{self._target_label(target.value)}"
        return _shorten(self._text(target), _LABEL_LIMIT)


def _differ(true_env: _Environment, false_env: _Environment) -> bool:
    return any(
        name in false_env and true_env[name] != false_env[name] for name in true_env
    )


class _Printer:
    def __init__(self, language: Language) -> None:
        self._language = language
        self._syntax = language.syntax
        self._names: dict[m.Node, str] = {}

    def lines(
        self, expression: m.Expr, leaves: dict[m.Node, str], width: int
    ) -> list[str]:
        self._names = dict(leaves)
        for node in m.walk(expression):
            if (
                isinstance(node, m.Literal)
                and isinstance(node.value, str)
                and len(node.value) > _LITERAL_LIMIT
            ):
                self._names.setdefault(
                    node,
                    _shorten(
                        json.dumps(node.value, ensure_ascii=False), _LITERAL_LIMIT
                    ),
                )
        return self._lines(expression, width)

    def _lines(self, expression: m.Expr, width: int) -> list[str]:
        named = self._names.get(expression)
        if named is not None:
            return [named]
        text = self._text(expression)
        if len(text) <= width:
            return [text]
        if isinstance(expression, m.Call):
            return self._call_lines(expression, width)
        if isinstance(expression, m.Sequence):
            return self._collection_lines(expression, width)
        if isinstance(expression, m.Unary):
            prefix = self._unary_prefix(expression)
            inner = self._lines(expression.operand, max(16, width - len(prefix)))
            if self._precedence(expression.operand) < self._precedence(expression):
                inner = _parenthesised(inner)
            return [
                prefix + inner[0],
                *(" " * len(prefix) + line for line in inner[1:]),
            ]
        pieces = self._pieces(expression)
        if pieces is None:
            return [text]
        lines: list[str] = []
        for prefix, piece, minimum in pieces:
            inner = self._lines(piece, max(16, width - len(prefix) - 1))
            if self._precedence(piece) < minimum:
                inner = _parenthesised(inner)
            lines.append(prefix + inner[0])
            lines += [" " * len(prefix) + line for line in inner[1:]]
        return lines

    def _call_lines(self, call: m.Call, width: int) -> list[str]:
        lines = [f"{self._text(call.func)}("]
        arguments = [("", argument) for argument in call.args] + [
            (self._keyword_prefix(keyword), keyword.value) for keyword in call.keywords
        ]
        for prefix, argument in arguments:
            inner = self._lines(argument, max(16, width - 4 - len(prefix)))
            lines.append(f"    {prefix}{inner[0]}")
            lines += [f"    {' ' * len(prefix)}{line}" for line in inner[1:]]
            lines[-1] += ","
        lines.append(")")
        return lines

    def _collection_lines(self, collection: m.Sequence, width: int) -> list[str]:
        opening, closing = self._syntax.brackets.get(collection.kind, ("(", ")"))
        lines = [opening]
        for element in collection.elements:
            inner = self._lines(element, max(16, width - 4))
            lines += [f"    {line}" for line in inner]
            lines[-1] += ","
        lines.append(closing)
        return lines

    def _text(self, expression: m.Expr) -> str:
        named = self._names.get(expression)
        if named is not None:
            return named
        if isinstance(expression, m.Call) and not any(
            isinstance(argument, m.Spread) for argument in expression.args
        ):
            arguments = [self._text(argument) for argument in expression.args] + [
                self._keyword_prefix(keyword) + self._text(keyword.value)
                for keyword in expression.keywords
            ]
            return f"{self._text(expression.func)}({', '.join(arguments)})"
        if isinstance(expression, m.Unary) and not _is_literal_expression(expression):
            operand = self._text(expression.operand)
            if self._precedence(expression.operand) < self._precedence(expression):
                operand = f"({operand})"
            return self._unary_prefix(expression) + operand
        pieces = self._pieces(expression)
        if pieces is None:
            if not self._names:
                return self._language.text(expression)
            return self._language.text_with(expression, self._names)
        return " ".join(
            prefix
            + (
                f"({self._text(piece)})"
                if self._precedence(piece) < minimum
                else self._text(piece)
            )
            for prefix, piece, minimum in pieces
        )

    def _keyword_prefix(self, keyword: m.Keyword) -> str:
        if keyword.arg is None:
            return self._language.profile.mapping_spread_prefix
        return f"{keyword.arg}{self._syntax.keyword_separator}"

    def _pieces(self, expression: m.Expr) -> list[tuple[str, m.Expr, int]] | None:
        operators = self._syntax.operators
        if isinstance(expression, m.Logical):
            word, level = operators[expression.op]
            return [
                ("" if index == 0 else f"{word} ", value, level + 1)
                for index, value in enumerate(expression.values)
            ]
        if (
            isinstance(expression, m.Binary)
            and expression.op not in self._syntax.unchained_operators
        ):
            level = self._precedence(expression)
            terms: list[tuple[str, m.Expr]] = []
            current: m.Expr = expression
            while (
                isinstance(current, m.Binary)
                and current not in self._names
                and self._precedence(current) == level
            ):
                terms.append((f"{operators[current.op][0]} ", current.right))
                current = current.left
            terms.reverse()
            return [("", current, level)] + [
                (prefix, term, level + 1) for prefix, term in terms
            ]
        if isinstance(expression, m.Conditional):
            if self._syntax.conditional_first:
                return [
                    ("", expression.test, 1),
                    ("? ", expression.body, 0),
                    (": ", expression.orelse, 0),
                ]
            return [
                ("", expression.body, 1),
                ("if ", expression.test, 1),
                ("else ", expression.orelse, 0),
            ]
        if isinstance(expression, m.Compare):
            level = self._syntax.compare_precedence + 1
            return [("", expression.left, level)] + [
                (f"{self._syntax.comparisons.get(op, op)} ", comparator, level)
                for op, comparator in zip(expression.ops, expression.comparators)
            ]
        return None

    def _unary_prefix(self, expression: m.Unary) -> str:
        return self._syntax.unary_prefixes.get(expression.op, expression.op)

    def _precedence(self, expression: m.Expr) -> int:
        if expression in self._names:
            return 13
        if isinstance(expression, (m.Logical, m.Binary)):
            return self._syntax.operators[expression.op][1]
        if isinstance(expression, m.Compare):
            return self._syntax.compare_precedence
        if isinstance(expression, m.Unary):
            return self._syntax.unary_precedence.get(expression.op, 11)
        if isinstance(expression, (m.Conditional, m.Function, m.AssignExpr)):
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


def _is_literal_expression(expression: m.Expr | None) -> bool:
    if isinstance(expression, m.Literal):
        return True
    if isinstance(expression, m.Unary) and expression.op in ("-", "+"):
        return isinstance(expression.operand, m.Literal) and isinstance(
            expression.operand.value, (int, float, complex)
        )
    if isinstance(expression, m.Sequence):
        return all(_is_literal_expression(element) for element in expression.elements)
    if isinstance(expression, m.Slice):
        return all(
            part is None or _is_literal_expression(part)
            for part in (expression.lower, expression.upper, expression.step)
        )
    if isinstance(expression, m.Mapping):
        return all(
            key is not None and _is_literal_expression(key) for key in expression.keys
        ) and all(_is_literal_expression(value) for value in expression.values)
    return False


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


def _pin_name(expression: m.Expr, fallback: str = "value") -> str:
    if isinstance(expression, m.Name):
        return expression.id
    if isinstance(expression, m.Member):
        return expression.attr
    return fallback


def _argument_name(argument: m.Expr, index: int) -> str:
    if isinstance(argument, (m.Name, m.Member)):
        return _pin_name(argument)
    return f"arg{index + 1}"


def _element_name(element: m.Expr, index: int) -> str:
    return _pin_name(element) if isinstance(element, (m.Name, m.Member)) else str(index)


def _flat_targets(target: m.Expr) -> list[m.Expr]:
    if isinstance(target, m.Sequence):
        return [leaf for element in target.elements for leaf in _flat_targets(element)]
    return [target]


def _assigned_names(target: m.Expr) -> list[str] | None:
    if isinstance(target, m.Name):
        return [target.id]
    if isinstance(target, m.Spread):
        names = _assigned_names(target.value)
        return [f"*{name}" for name in names] if names is not None else None
    if isinstance(target, m.Sequence):
        collected: list[str] = []
        for element in target.elements:
            names = _assigned_names(element)
            if names is None:
                return None
            collected.extend(names)
        return collected
    return None


def _unwrap_call(value: m.Expr) -> tuple[m.Call | None, bool]:
    if isinstance(value, m.Call):
        return value, False
    if isinstance(value, m.Await) and isinstance(value.value, m.Call):
        return value.value, True
    return None, False


def _split_attribute(expression: m.Member) -> tuple[list[str], m.Expr]:
    attributes: list[str] = []
    current: m.Expr = expression
    while isinstance(current, m.Member):
        attributes.insert(0, current.attr)
        current = current.value
    return attributes, current


def _is_none(expression: m.Expr) -> bool:
    return isinstance(expression, m.Literal) and expression.value is None


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


def _external_is_pure(profile: Profile, external: str) -> bool:
    return (
        external in profile.pure_externals
        or external.split(".")[0] in profile.pure_external_modules
        or external.rsplit(".", 1)[-1][:1].isupper()
    )


def _is_class_variable(module: ParsedModule, annotation: m.TypeExpr) -> bool:
    return (
        isinstance(annotation, m.TypeName)
        and annotation.dotted.rsplit(".", 1)[-1]
        in module.language.profile.types.class_variable
    )


def _definition_name(statement: m.FunctionDef | m.ClassDef) -> str:
    if isinstance(statement, m.FunctionDef):
        return statement.function.name
    return statement.cls.name


def _members_of(cls: m.ClassDecl, module: ParsedModule) -> dict[str, _Member]:
    members: dict[str, _Member] = {}
    for statement in cls.body:
        if (
            isinstance(statement, m.Assign)
            and statement.annotation is not None
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], m.Name)
        ):
            members.setdefault(
                statement.targets[0].id, _Member(statement.annotation, module)
            )
        elif isinstance(statement, m.FunctionDef):
            function = statement.function
            if function.is_property:
                members.setdefault(function.name, _Member(function.returns, module))
            else:
                members.setdefault(function.name, _Member(None, module, is_method=True))
    initializer = next(
        (
            statement.function
            for statement in cls.body
            if isinstance(statement, m.FunctionDef)
            and statement.function.is_constructor
            and not statement.function.is_async
        ),
        None,
    )
    if initializer is not None:
        for name, annotation in _initializer_assignments(initializer, module):
            members.setdefault(name, _Member(annotation, module))
    return members


def _initializer_assignments(
    initializer: m.FunctionDecl, module: ParsedModule
) -> Iterator[tuple[str, m.TypeExpr | None]]:
    receiver = (
        initializer.implicit_receiver or module.language.profile.instance_receiver
    )
    parameters = {
        parameter.name: parameter.annotation for parameter in initializer.params
    }
    for node in m.walk(initializer):
        if not isinstance(node, m.Assign):
            continue
        for target in node.targets:
            if not (
                isinstance(target, m.Member)
                and isinstance(target.value, m.Name)
                and target.value.id == receiver
            ):
                continue
            if node.annotation is not None:
                yield target.attr, node.annotation
            else:
                yield target.attr, (
                    parameters.get(node.value.id)
                    if isinstance(node.value, m.Name)
                    else None
                )


def _module_variables(
    module: ParsedModule,
) -> dict[str, tuple[m.TypeExpr | None, m.Expr | None]]:
    variables: dict[str, tuple[m.TypeExpr | None, m.Expr | None]] = {}
    pending: list[m.Stmt] = list(module.body)
    while pending:
        statement = pending.pop(0)
        if isinstance(statement, m.Assign):
            if (
                statement.annotation is not None
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], m.Name)
            ):
                variables[statement.targets[0].id] = (
                    statement.annotation,
                    statement.value,
                )
                continue
            for target in statement.targets:
                for name in _assigned_names(target) or []:
                    variables.setdefault(name.lstrip("*"), (None, statement.value))
        elif isinstance(statement, m.If):
            pending.extend([*statement.body, *statement.orelse])
        elif isinstance(statement, m.Try):
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


def _attribute_counts(definition: m.FunctionDecl) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in m.walk(definition):
        if isinstance(node, m.Member):
            name = m.dotted_name(node)
            if name is not None:
                counts[name] += 1
    return counts


def _free_names(expression: m.Expr) -> list[str]:
    bound: set[str] = set()
    for node in m.walk(expression):
        if isinstance(node, m.Comprehension):
            bound.update(node.bound)
        elif isinstance(node, m.Function):
            bound.update(parameter.name for parameter in node.params)
        elif isinstance(node, m.AssignExpr):
            bound.add(node.target.id)
    names: list[str] = []
    for node in m.walk(expression):
        if (
            isinstance(node, m.Name)
            and not node.store
            and node.id not in bound
            and node.id not in names
        ):
            names.append(node.id)
    return names


def _suspends(expression: m.Expr) -> bool:
    return any(
        isinstance(node, (m.Await, m.Yield, m.AssignExpr))
        for node in m.walk(expression)
    )


def _contains_return(statements: Sequence[m.Stmt]) -> bool:
    pending: list[m.Node] = list(statements)
    while pending:
        node = pending.pop()
        if isinstance(node, m.Return):
            return True
        if isinstance(node, (m.FunctionDef, m.ClassDef, m.Function)):
            continue
        pending.extend(m.children(node))
    return False


def _always_terminates(statements: Sequence[m.Stmt]) -> bool:
    return any(_terminates(statement) for statement in statements)


def _terminates(statement: m.Stmt) -> bool:
    if isinstance(statement, (m.Return, m.Raise)):
        return True
    if isinstance(statement, m.If):
        return _always_terminates(statement.body) and _always_terminates(
            statement.orelse
        )
    return False
