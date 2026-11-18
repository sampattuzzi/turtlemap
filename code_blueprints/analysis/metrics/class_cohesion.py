from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from code_blueprints.analysis.metrics.code_graph import CodeGraph, Node, brief
from code_blueprints.analysis.metrics.formulas import FORMULAS
from code_blueprints.analysis.metrics.groups import cohesion_label, connected_groups

HUB_SHARE = 0.5

CONSTRUCTORS = frozenset({"__init__", "__post_init__", "__new__", "constructor"})


@dataclass
class _MethodUse:
    methods: list[Node]
    fields: set[str]
    touches: dict[str, set[str]]
    calls: dict[str, set[str]]
    usage: Counter[str]
    hubs: set[str]


class ClassCohesion:
    def __init__(self, code: CodeGraph) -> None:
        self._code = code

    def measure(self, holder: Node) -> dict[str, Any]:
        use = self._method_use(holder)
        base = {
            "node": brief(holder),
            "methods": len(use.methods),
            "fields": len(use.fields),
            "field_use": {self._name(f): n for f, n in use.usage.most_common()},
            "formula": FORMULAS["class"],
        }
        if len(use.methods) < 2:
            text = f"class {holder.label}: {len(use.methods)} method(s) besides the constructor, too few to measure cohesion."
            return {**base, "groups": None, "label": "n/a", "text": text}
        groups = connected_groups(use.touches, use.calls, set())
        without_hubs = (
            connected_groups(use.touches, use.calls, use.hubs) if use.hubs else groups
        )
        return {
            **base,
            "groups": len(groups),
            "groups_without_hubs": len(without_hubs),
            "hubs": sorted(self._name(f) for f in use.hubs),
            "members": [sorted(self._name(i) for i in g) for g in groups],
            "label": cohesion_label(len(groups)),
            "text": "\n".join(self._lines(holder, use, groups, without_hubs)),
        }

    def _method_use(self, holder: Node) -> _MethodUse:
        methods = [
            m
            for m in holder.children
            if m.kind == "method" and m.name not in CONSTRUCTORS
        ]
        fields = {f.id for f in self._class_fields(holder)}
        touches = {m.id: self._fields_touched(m, fields) for m in methods}
        calls = {m.id: self._methods_called(m, touches.keys()) for m in methods}
        usage = Counter(f for touched in touches.values() for f in touched)
        hubs = (
            {f for f, n in usage.items() if n / len(methods) > HUB_SHARE}
            if len(methods) >= 4
            else set()
        )
        return _MethodUse(methods, fields, touches, calls, usage, hubs)

    def _fields_touched(self, method: Node, fields: set[str]) -> set[str]:
        return {
            e.target
            for e in self._code.outgoing.get(method.id, [])
            if e.target in fields and e.kinds & {"reads", "writes"}
        }

    def _methods_called(self, method: Node, methods: Collection[str]) -> set[str]:
        return {
            e.target
            for e in self._code.outgoing.get(method.id, [])
            if e.target in methods
        }

    def _class_fields(self, holder: Node) -> list[Node]:
        seen: set[str] = set()
        fields: list[Node] = []
        stack = [holder]
        while stack:
            current = stack.pop()
            if current.id in seen:
                continue
            seen.add(current.id)
            fields += [f for f in current.children if f.kind == "field"]
            stack += [
                self._code.nodes[e.target]
                for e in self._code.outgoing.get(current.id, [])
                if "inherits" in e.kinds and e.target.startswith("cls:")
            ]
        return fields

    def _lines(
        self,
        holder: Node,
        use: _MethodUse,
        groups: list[list[str]],
        without_hubs: list[list[str]],
    ) -> list[str]:
        lines = [
            f"class {holder.label}: {cohesion_label(len(groups))} cohesion, {len(groups)} group(s) of methods (LCOM4 = {len(groups)})",
            f"  {len(use.methods)} methods besides the constructor, {len(use.fields)} fields",
        ]
        if len(groups) > 1:
            lines += [
                f"  group {n}: {', '.join(sorted(self._name(i) for i in g))}"
                for n, g in enumerate(groups, 1)
            ]
        if use.hubs:
            lines.append(self._hub_line(use.hubs, len(groups), len(without_hubs)))
        if use.usage:
            lines.append(
                "  field use: "
                + ", ".join(
                    f"{self._name(f)}×{n}" for f, n in use.usage.most_common(10)
                )
            )
        lines.append(f"formula: {FORMULAS['class']}")
        return lines

    def _hub_line(self, hubs: set[str], grouped: int, grouped_without: int) -> str:
        names = ", ".join(sorted(self._name(f) for f in hubs))
        verdict = (
            "so the score flatters the class"
            if grouped_without > grouped
            else "so they are not what holds it together"
        )
        return f"  hub fields used by most methods: {names}. Without them: {grouped_without} group(s), {verdict}."

    def _name(self, node_id: str) -> str:
        return self._code.nodes[node_id].name
