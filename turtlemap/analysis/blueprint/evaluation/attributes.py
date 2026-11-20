from collections import Counter
from collections.abc import Callable, Sequence

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.canvas import Graph, GraphNode
from turtlemap.analysis.blueprint.lookups import TypeLookups
from turtlemap.analysis.blueprint.scope import Scope
from turtlemap.analysis.blueprint.text import pin_name
from turtlemap.analysis.blueprint.values import Value
from turtlemap.analysis.types import UNKNOWN, PinType
from turtlemap.analysis.workspace.parsed import ParsedModule, SymbolRef

_BaseKey = tuple[str | None, str | None, str | None, str | None]


class AttributeReads:
    def __init__(
        self,
        lookups: TypeLookups,
        scope: Scope,
        graph: Graph,
        function: m.FunctionDecl,
        evaluate: Callable[[m.Expr], Value],
    ) -> None:
        self._lookups = lookups
        self._scope = scope
        self._graph = graph
        self._evaluate = evaluate
        self._attribute_counts = _attribute_counts(function)
        self._breaks: dict[_BaseKey, GraphNode] = {}
        self._getters: dict[tuple[_BaseKey, str], Value] = {}
        self._fields: dict[tuple[_BaseKey, str], Value] = {}

    def read(self, expression: m.Member) -> Value:
        attributes, base = _split_attribute(expression)
        if (
            isinstance(base, m.Name)
            and not self._scope.is_local(base.id)
            and base.id not in self._lookups.module_variables
        ):
            return self._scope.global_value(
                f"{base.id}.{'.'.join(attributes)}", expression.line
            )
        current = self._evaluate(base)
        prefix = base.id if isinstance(base, m.Name) else None
        base_name = pin_name(base)
        index = 0
        while index < len(attributes):
            end = self._group_end(prefix, attributes, index)
            getter_at = self._first_getter(current, attributes, index, end)
            if getter_at is not None and getter_at[0] == index:
                current = self._getter_read(
                    current, base_name, attributes[index], getter_at[1], expression.line
                )
                base_name = attributes[index]
                prefix = f"{prefix}.{base_name}" if prefix is not None else None
                index += 1
                continue
            if getter_at is not None:
                end = getter_at[0] - 1
            name = ".".join(attributes[index : end + 1])
            pin_type, annotation = self._lookups.attribute_chain(
                current, attributes[index : end + 1]
            )
            current = self._break_read(
                current, base_name, name, pin_type, annotation, expression.line
            )
            base_name = attributes[end]
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

    def _first_getter(
        self, current: Value, attributes: Sequence[str], start: int, end: int
    ) -> tuple[int, SymbolRef] | None:
        for position in range(start, end + 1):
            owner = (
                current.type
                if position == start
                else self._lookups.attribute_chain(current, attributes[start:position])[
                    0
                ]
            )
            getter = self._getter(owner, attributes[position])
            if getter is not None:
                return position, getter
        return None

    def _getter(self, owner: PinType, attribute: str) -> SymbolRef | None:
        workspace = self._lookups.workspace
        if owner.ref is None or workspace.parsed_class(owner.ref) is None:
            return None
        found = workspace.find_method(owner.ref, attribute)
        return (
            found if found is not None and workspace.reads_as_property(found) else None
        )

    def _getter_read(
        self, base: Value, base_name: str, attribute: str, getter: SymbolRef, line: int
    ) -> Value:
        frame = self._graph.frame_of(base)
        key = (_base_key(base, frame), attribute)
        cached = self._getters.get(key)
        if cached is not None:
            return cached
        with self._graph.inside(frame):
            node = self._graph.add(
                "method", f"{base_name}.{attribute}", line, target=getter
            )
        self._graph.connect(node, self._lookups.profile.instance_receiver, base)
        value = self._graph.output(node, attribute, self._returned_by(getter))
        self._getters[key] = value
        return value

    def _returned_by(self, getter: SymbolRef) -> PinType:
        workspace = self._lookups.workspace
        function = workspace.parsed_function(getter)
        module = workspace.module(getter.path)
        if function is None or module is None or function.node.returns is None:
            return UNKNOWN
        return self._lookups.resolver(module).annotation(function.node.returns)

    def _break_read(
        self,
        base: Value,
        base_name: str,
        attribute: str,
        pin_type: PinType,
        annotation: tuple[m.TypeExpr, ParsedModule] | None,
        line: int,
    ) -> Value:
        frame = self._graph.frame_of(base)
        key = _base_key(base, frame)
        node = self._breaks.get(key)
        if node is None:
            label = _type_name(base.type) or base_name
            with self._graph.inside(frame):
                node = self._graph.add(
                    "break", f"Break {label}", line, target=base.type.ref
                )
            self._graph.connect(node, base_name, base)
            self._breaks[key] = node
        read = self._fields.get((key, attribute))
        if read is None:
            read = self._graph.output(node, attribute, pin_type, annotation)
            self._fields[(key, attribute)] = read
        return read


def _base_key(base: Value, frame: str | None) -> _BaseKey:
    return (frame, base.node, base.pin, base.literal)


def _split_attribute(expression: m.Member) -> tuple[list[str], m.Expr]:
    attributes: list[str] = []
    current: m.Expr = expression
    while isinstance(current, m.Member):
        attributes.insert(0, current.attr)
        current = current.value
    return attributes, current


def _attribute_counts(definition: m.FunctionDecl) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in m.walk(definition):
        if isinstance(node, m.Member):
            name = m.dotted_name(node)
            if name is not None:
                counts[name] += 1
    return counts


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
