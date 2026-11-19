from typing import Any

from turtlemap.analysis.metrics.code_graph import CodeGraph, Edge, Node, brief
from turtlemap.analysis.metrics.coupling import Coupling
from turtlemap.analysis.metrics.formulas import FORMULAS
from turtlemap.analysis.metrics.groups import cohesion_label, connected_groups

MEMBER_KINDS = frozenset({"class", "function"})


class GroupCohesion:
    def __init__(self, code: CodeGraph, coupling: Coupling) -> None:
        self._code = code
        self._coupling = coupling

    def measure(self, node: Node) -> dict[str, Any]:
        members = _members(node)
        wiring = self._wiring(node, members)
        groups = connected_groups(wiring.touches, wiring.links, set())
        verdict = cohesion_label(len(groups)) if len(members) > 1 else "n/a"
        return {
            "node": brief(node),
            "members": len(members),
            "groups": len(groups),
            "group_members": [sorted(self._name(i) for i in g) for g in groups],
            "internal": wiring.internal,
            "external": wiring.external,
            "relational": wiring.relational(),
            "label": verdict,
            "formula": FORMULAS[node.kind],
            "text": "\n".join(self._lines(node, members, groups, wiring)),
        }

    def _wiring(self, node: Node, members: list[Node]) -> "_Wiring":
        owner = {i: m.id for m in members for i in self._code.subtree(m)}
        constants = {c.id for c in node.children if c.kind == "constant"}
        wiring = _Wiring(owner, members, constants)
        inside = self._code.subtree(node)
        for i in inside:
            for edge in self._code.outgoing.get(i, []):
                if edge.target in inside:
                    wiring.add_internal(edge)
                elif self._code.module_of(edge.target) is not None:
                    wiring.external += 1
        return wiring

    def _lines(
        self,
        node: Node,
        members: list[Node],
        groups: list[list[str]],
        wiring: "_Wiring",
    ) -> list[str]:
        lines = [
            f"{node.kind} {node.label}: {len(members)} member(s) in {len(groups)} linked group(s)"
            + _relational_text(wiring)
        ]
        if len(groups) > 1:
            lines += self._split_lines(groups)
        if node.kind == "module":
            lines.append("  " + _instability_text(self._coupling.instability(node)))
        lines.append(f"formula: {FORMULAS[node.kind]}")
        return lines

    def _split_lines(self, groups: list[list[str]]) -> list[str]:
        lines = [
            f"  group {n}: {', '.join(sorted(self._name(i) for i in g))}"
            for n, g in enumerate(groups, 1)
            if len(g) > 1
        ]
        loners = [self._name(g[0]) for g in groups if len(g) == 1]
        if loners:
            lines.append(
                f"  unlinked to anything else here: {', '.join(sorted(loners))}"
            )
        return lines

    def _name(self, node_id: str) -> str:
        return self._code.nodes[node_id].name


class _Wiring:
    def __init__(
        self, owner: dict[str, str], members: list[Node], constants: set[str]
    ) -> None:
        self.owner = owner
        self.constants = constants
        self.links: dict[str, set[str]] = {m.id: set() for m in members}
        self.touches: dict[str, set[str]] = {m.id: set() for m in members}
        self.internal = 0
        self.external = 0

    def add_internal(self, edge: Edge) -> None:
        self.internal += 1
        a, b = self.owner.get(edge.source), self.owner.get(edge.target)
        if a and b and a != b:
            self.links[a].add(b)
        if a and edge.target in self.constants:
            self.touches[a].add(edge.target)
        if b and edge.source in self.constants:
            self.touches[b].add(edge.source)

    def relational(self) -> float | None:
        total = self.internal + self.external
        return self.internal / total if total else None


def _members(node: Node) -> list[Node]:
    kinds = MEMBER_KINDS if node.kind == "module" else {"module", "package"}
    return [m for m in node.children if m.kind in kinds]


def _relational_text(wiring: _Wiring) -> str:
    relational = wiring.relational()
    if relational is None:
        return ""
    return f", relational cohesion {relational:.2f} ({wiring.internal} links inside, {wiring.external} to other project modules)"


def _instability_text(numbers: dict[str, Any]) -> str:
    return f"used by {numbers['ca']} project module(s), uses {numbers['ce']}: instability {numbers['instability']:.2f}"
