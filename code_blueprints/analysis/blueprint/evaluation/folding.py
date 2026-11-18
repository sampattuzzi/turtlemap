from collections.abc import Callable
from typing import TypeVar

from code_blueprints.analysis import model as m
from code_blueprints.analysis.blueprint.callees import Callees
from code_blueprints.analysis.blueprint.canvas import Graph, GraphNode
from code_blueprints.analysis.blueprint.code_shapes import is_literal_expression
from code_blueprints.analysis.blueprint.lookups import TypeLookups
from code_blueprints.analysis.blueprint.printer import Printer
from code_blueprints.analysis.blueprint.scope import Scope
from code_blueprints.analysis.blueprint.text import shorten, unused_name
from code_blueprints.analysis.blueprint.values import (
    BOOL,
    FLOAT,
    Folded,
    Value,
    select_type,
)
from code_blueprints.analysis.types import UNKNOWN, PinType

_EXPRESSION_WIDTH = 44
_INPUT_NAME_LIMIT = 28
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
_Expression = TypeVar("_Expression", bound=m.Expr)
_Parts = Callable[[m.Expr], list[m.Expr] | None]
_TypeOf = Callable[[m.Expr], PinType]
_OperationType = Callable[[m.Expr, _TypeOf], PinType]


class Folding:
    def __init__(
        self,
        lookups: TypeLookups,
        callees: Callees,
        scope: Scope,
        graph: Graph,
        evaluate: Callable[[m.Expr], Value],
    ) -> None:
        self._lookups = lookups
        self._callees = callees
        self._scope = scope
        self._graph = graph
        self._evaluate = evaluate
        self._module = lookups.module
        self._profile = lookups.profile
        self._printer = Printer(lookups.module.language)

    def folds(self, expression: m.Expr, *, named: bool) -> bool:
        if isinstance(expression, m.Name) or is_literal_expression(expression):
            return False
        if self._parts(expression) is None:
            return False
        computations, operations = self._counts(expression)
        return computations >= 2 or (named and operations >= 1)

    def fold(self, expression: m.Expr) -> Folded:
        inputs: dict[str, Value] = {}
        values: dict[int, Value] = {}
        types: dict[int, PinType] = {}
        leaves: dict[m.Node, str] = {}
        self._walk(expression, inputs, values, types, leaves)
        return Folded(
            list(inputs.items()),
            types.get(id(expression), UNKNOWN),
            self._printer.lines(expression, leaves, _EXPRESSION_WIDTH),
        )

    def expression(self, expression: m.Expr, name: str) -> Value:
        return self.node(self.fold(expression), name, expression.line)

    def node(self, folded: Folded, name: str, line: int) -> Value:
        title = name or ("Check" if folded.result.cat == "bool" else "Calculate")
        node = self._graph.add("expr", title, line)
        self.write(node, folded)
        return self._graph.output(node, "", folded.result)

    def inline_condition(
        self, expression: m.Expr, create: Callable[[], GraphNode]
    ) -> GraphNode:
        folded = self.fold(expression)
        node = create()
        self.write(node, folded)
        return node

    def write(self, node: GraphNode, folded: Folded) -> None:
        node.expression = folded.lines
        for pin, value in folded.inputs:
            self._graph.connect(node, pin, value)

    def select_on(
        self,
        condition: Value | Folded,
        when_true: Value,
        when_false: Value,
        line: int,
    ) -> Value:
        if isinstance(condition, Value):
            return self._scope.select(condition, when_true, when_false, line)
        if when_true == when_false:
            return when_true
        node = self._graph.add("select", "Select", line)
        self.write(node, condition)
        self._graph.connect(node, "if true", when_true)
        self._graph.connect(node, "if false", when_false)
        return self._graph.output(node, "", select_type(when_true, when_false))

    def _walk(
        self,
        expression: m.Expr,
        inputs: dict[str, Value],
        values: dict[int, Value],
        types: dict[int, PinType],
        leaves: dict[m.Node, str],
    ) -> None:
        literal = self._lookups.literal(expression)
        if literal is not None:
            types[id(expression)] = literal.type
            return
        if isinstance(expression, m.Name):
            if self._scope.is_local(expression.id):
                value = inputs.get(expression.id) or self._scope.value_of(
                    expression.id, expression.line
                )
                inputs[expression.id] = value
                values[id(expression)] = value
                types[id(expression)] = value.type
            else:
                types[id(expression)] = UNKNOWN
            return
        parts = self._parts(expression)
        if parts is None:
            value = self._evaluate(expression)
            if value.node is not None:
                name = unused_name(
                    shorten(self._module.language.text(expression), _INPUT_NAME_LIMIT),
                    set(inputs),
                )
                inputs[name] = value
                leaves[expression] = name
            values[id(expression)] = value
            types[id(expression)] = value.type
            return
        for part in parts:
            self._walk(part, inputs, values, types, leaves)
        types[id(expression)] = self._folded_type(expression, types, values)

    def _on_project_object(self, expression: m.Expr) -> bool:
        root = expression
        while isinstance(root, (m.Member, m.Subscript)):
            root = root.value
        if not isinstance(root, m.Name) or not self._scope.is_local(root.id):
            return False
        binding = self._scope.env.get(root.id)
        return isinstance(binding, Value) and binding.type.ref is not None

    def _parts(self, expression: m.Expr) -> list[m.Expr] | None:
        structural = _STRUCTURAL_PARTS.get(type(expression))
        if structural is not None:
            return structural(expression)
        if isinstance(expression, m.Member):
            return self._member_parts(expression)
        if isinstance(expression, m.Call) and self._folds_call(expression):
            return [
                *self._method_receiver(expression.func),
                *expression.args,
                *(keyword.value for keyword in expression.keywords),
            ]
        return None

    def _member_parts(self, expression: m.Member) -> list[m.Expr] | None:
        dotted = m.dotted_name(expression)
        if dotted is not None and not self._scope.is_local(dotted.split(".")[0]):
            return []
        if self._on_project_object(expression):
            return None
        return [expression.value]

    def _method_receiver(self, function: m.Expr) -> list[m.Expr]:
        if not isinstance(function, m.Member):
            return []
        dotted = m.dotted_name(function)
        if dotted is not None and not self._scope.is_local(dotted.split(".")[0]):
            return []
        return [function.value]

    def _folds_call(self, call: m.Call) -> bool:
        if any(isinstance(argument, m.Spread) for argument in call.args) or any(
            keyword.arg is None for keyword in call.keywords
        ):
            return False
        function = call.func
        if isinstance(function, m.Name):
            return not self._scope.is_local(function.id) and self._callees.folds_global(
                function.id
            )
        if isinstance(function, m.Member):
            dotted = m.dotted_name(function)
            if dotted is not None and not self._scope.is_local(dotted.split(".")[0]):
                return self._callees.folds_global(dotted)
            return (
                function.attr in self._profile.pure_methods
                and not self._on_project_object(function.value)
            )
        return False

    def _counts(self, expression: m.Expr) -> tuple[int, int]:
        if isinstance(expression, m.Name) or is_literal_expression(expression):
            return 0, 0
        parts = self._parts(expression)
        if parts is None:
            return 0, 0
        computations = int(isinstance(expression, _COMPUTATIONS))
        operations = int(isinstance(expression, _OPERATIONS))
        for part in parts:
            more, extra = self._counts(part)
            computations += more
            operations += extra
        return computations, operations

    def _folded_type(
        self,
        expression: m.Expr,
        types: dict[int, PinType],
        values: dict[int, Value],
    ) -> PinType:
        def of(part: m.Expr) -> PinType:
            return types.get(id(part), UNKNOWN)

        operation = _OPERATION_TYPES.get(type(expression))
        if operation is not None:
            return operation(expression, of)
        if isinstance(expression, m.Call):
            return self._callees.folded_call_type(expression, types)
        if isinstance(expression, m.Subscript):
            container = values.get(id(expression.value))
            return (
                self._lookups.item(container, expression.index)
                if container is not None
                else UNKNOWN
            )
        return UNKNOWN


def _parts_of(
    kind: type[_Expression], take: Callable[[_Expression], list[m.Expr] | None]
) -> tuple[type[m.Expr], _Parts]:
    def run(expression: m.Expr) -> list[m.Expr] | None:
        assert isinstance(expression, kind)
        return take(expression)

    return kind, run


def _logical_parts(expression: m.Logical) -> list[m.Expr]:
    return list(expression.values)


def _binary_parts(expression: m.Binary) -> list[m.Expr]:
    return [expression.left, expression.right]


def _unary_parts(expression: m.Unary) -> list[m.Expr]:
    return [expression.operand]


def _compare_parts(expression: m.Compare) -> list[m.Expr]:
    return [expression.left, *expression.comparators]


def _conditional_parts(expression: m.Conditional) -> list[m.Expr]:
    return [expression.test, expression.body, expression.orelse]


def _subscript_parts(expression: m.Subscript) -> list[m.Expr]:
    return [expression.value, expression.index]


def _slice_parts(expression: m.Slice) -> list[m.Expr]:
    return [
        part
        for part in (expression.lower, expression.upper, expression.step)
        if part is not None
    ]


def _sequence_parts(expression: m.Sequence) -> list[m.Expr] | None:
    if any(isinstance(element, m.Spread) for element in expression.elements):
        return None
    return list(expression.elements)


def _typed(
    kind: type[_Expression], rule: Callable[[_Expression, _TypeOf], PinType]
) -> tuple[type[m.Expr], _OperationType]:
    def run(expression: m.Expr, of: _TypeOf) -> PinType:
        assert isinstance(expression, kind)
        return rule(expression, of)

    return kind, run


def _compare_type(expression: m.Compare, of: _TypeOf) -> PinType:
    return BOOL


def _logical_type(expression: m.Logical, of: _TypeOf) -> PinType:
    parts = [of(value) for value in expression.values]
    return BOOL if all(part.cat == "bool" for part in parts) else parts[0]


def _unary_type(expression: m.Unary, of: _TypeOf) -> PinType:
    return BOOL if expression.op == "not" else of(expression.operand)


def _binary_type(expression: m.Binary, of: _TypeOf) -> PinType:
    left, right = of(expression.left), of(expression.right)
    if left.cat != "any" and left.cat == right.cat:
        return left
    if {left.cat, right.cat} == {"int", "float"}:
        return FLOAT
    return left if left.cat == "str" else UNKNOWN


def _conditional_type(expression: m.Conditional, of: _TypeOf) -> PinType:
    body, orelse = of(expression.body), of(expression.orelse)
    return body if body.cat == orelse.cat else UNKNOWN


_STRUCTURAL_PARTS = dict(
    [
        _parts_of(m.Logical, _logical_parts),
        _parts_of(m.Binary, _binary_parts),
        _parts_of(m.Unary, _unary_parts),
        _parts_of(m.Compare, _compare_parts),
        _parts_of(m.Conditional, _conditional_parts),
        _parts_of(m.Subscript, _subscript_parts),
        _parts_of(m.Slice, _slice_parts),
        _parts_of(m.Sequence, _sequence_parts),
    ]
)
_OPERATION_TYPES = dict(
    [
        _typed(m.Compare, _compare_type),
        _typed(m.Logical, _logical_type),
        _typed(m.Unary, _unary_type),
        _typed(m.Binary, _binary_type),
        _typed(m.Conditional, _conditional_type),
    ]
)
