from collections import Counter
from collections.abc import Callable, Sequence

from code_blueprints.analysis import model as m
from code_blueprints.analysis.blueprint.canvas import Graph, GraphNode
from code_blueprints.analysis.blueprint.lookups import TypeLookups
from code_blueprints.analysis.blueprint.scope import Scope
from code_blueprints.analysis.blueprint.text import pin_name
from code_blueprints.analysis.blueprint.values import Value
from code_blueprints.analysis.types import PinType
from code_blueprints.analysis.workspace.parsed import ParsedModule


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
        self._breaks: dict[tuple[str | None, str | None, str | None], GraphNode] = {}

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

    def _break_read(
        self,
        base: Value,
        base_name: str,
        attribute: str,
        pin_type: PinType,
        annotation: tuple[m.TypeExpr, ParsedModule] | None,
        line: int,
    ) -> Value:
        key = (base.node, base.pin, base.literal)
        node = self._breaks.get(key)
        if node is None:
            label = _type_name(base.type) or base_name
            node = self._graph.add(
                "break", f"Break {label}", line, target=base.type.ref
            )
            self._graph.connect(node, base_name, base)
            self._breaks[key] = node
        existing = node.output(attribute)
        if existing is not None:
            return Value(existing.type, node.id, existing.name)
        return self._graph.output(node, attribute, pin_type, annotation)


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
