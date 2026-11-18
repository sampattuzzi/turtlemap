from collections import Counter
from typing import Any

from code_blueprints.analysis.metrics.code_graph import (
    FunctionGraph,
    Node,
    brief,
    child_counts,
    CodeGraph,
)
from code_blueprints.analysis.metrics.cohesion import Cohesion
from code_blueprints.analysis.metrics.coupling import Coupling
from code_blueprints.analysis.metrics.formulas import FORMULAS
from code_blueprints.analysis.metrics.function_cohesion import node_title
from code_blueprints.analysis.metrics.size import (
    SIZE_FORMULA,
    Sizes,
    describe_size,
)

TABLE_HEADER = "module                                       members groups internal  Ca  Ce  instability  classes that split"


class Structure:
    def __init__(
        self, overview: dict[str, Any], function_graph: FunctionGraph | None = None
    ) -> None:
        self._code = CodeGraph(overview)
        self._coupling = Coupling(self._code)
        self._cohesion = Cohesion(self._code, self._coupling, function_graph)
        self._sizes = Sizes(self._code)

    @property
    def nodes(self) -> dict[str, Node]:
        return self._code.nodes

    def resolve(self, name: str) -> Node:
        return self._code.resolve(name)

    def find(self, text: str, limit: int = 30) -> dict[str, Any]:
        return self._code.find(text, limit)

    def tree(self, name: str | None = None, depth: int = 2) -> dict[str, Any]:
        return self._code.tree(name, depth)

    def cohesion(self, name: str) -> dict[str, Any]:
        return self._cohesion.cohesion(name)

    def coupling(self, first: str, second: str) -> dict[str, Any]:
        return self._coupling.coupling(first, second)

    def instability(self, module: Node, include_tests: bool = False) -> dict[str, Any]:
        return self._coupling.instability(module, include_tests)

    def describe(self, name: str) -> dict[str, Any]:
        node = self._code.resolve(name)
        inside = self._code.subtree(node)
        level = "module" if node.kind in ("package", "module", "root") else "symbol"
        uses = self._code.lift(
            (
                e
                for i in inside
                for e in self._code.outgoing.get(i, [])
                if e.target not in inside
            ),
            lambda e: e.target,
            level,
        )
        used_by = self._code.lift(
            (
                e
                for i in inside
                for e in self._code.incoming.get(i, [])
                if e.source not in inside
            ),
            lambda e: e.source,
            level,
        )
        lines = [f"{node.kind} {node.label} ({node.place})"]
        size = self._sizes.of(node)
        if size:
            lines.append(f"size: {describe_size(node.kind, size)}")
        if node.children:
            lines.append(f"contains {child_counts(node)}")
        lines += _relations("depends on", uses) + _relations("used by", used_by)
        if node.kind == "module" and node.path:
            silent = sorted(
                path
                for path in self._code.imports.get(node.path, set())
                if f"mod:{path}" not in {u for u, _ in uses}
            )
            if silent:
                lines.append(
                    "imports without a recorded use (re-exports or types only): "
                    + ", ".join(silent)
                )
        return {
            "node": brief(node),
            "size": size,
            "depends_on": [_relation_json(self._code.nodes[i], c) for i, c in uses],
            "used_by": [_relation_json(self._code.nodes[i], c) for i, c in used_by],
            "text": "\n".join(lines),
        }

    def report(self, include_tests: bool = False, top: int = 12) -> dict[str, Any]:
        modules = [
            n
            for n in self._code.nodes.values()
            if n.kind == "module" and (include_tests or not self._code.is_test(n))
        ]
        rows = [
            self._module_row(module, include_tests)
            for module in sorted(modules, key=lambda m: m.id)
        ]
        pairs = self._coupling.module_pairs(modules, include_tests)
        oversized = self._sizes.oversized(include_tests)
        lines = [
            TABLE_HEADER,
            *(_row_line(row) for row in rows),
            "",
            *_pair_lines(pairs, top),
            "",
            *_oversized_lines(oversized, top),
            "",
            f"cohesion: {FORMULAS['module']}",
            f"class cohesion: {FORMULAS['class']}",
            FORMULAS["instability"],
            f"coupling: {FORMULAS['coupling']}",
            SIZE_FORMULA,
        ]
        return {
            "modules": rows,
            "pairs": pairs[: top * 3],
            "oversized": oversized[: top * 3],
            "text": "\n".join(lines),
        }

    def _module_row(self, module: Node, include_tests: bool) -> dict[str, Any]:
        group = self._cohesion.groups.measure(module)
        classes = [
            self._cohesion.classes.measure(c)
            for c in module.children
            if c.kind == "class"
            and sum(1 for m in c.children if m.kind == "method") >= 2
        ]
        return {
            "module": module.path,
            "members": group["members"],
            "groups": group["groups"],
            "relational": group["relational"],
            **self._coupling.instability(module, include_tests),
            "split_classes": [
                {"class": c["node"]["qual"], "groups": c["groups"]}
                for c in classes
                if isinstance(c["groups"], int) and c["groups"] > 1
            ],
        }

    def blueprint(self, name: str) -> dict[str, Any]:
        node = self._code.resolve(name)
        graph = self._cohesion.functions.graph(node)
        titles = {n["id"]: node_title(n) for n in graph["nodes"]}
        feeds: dict[str, list[str]] = {}
        for edge in graph["edges"]:
            feeds.setdefault(edge["to"], []).append(
                f"{edge['tp']}←{edge['from']}.{edge['fp']}"
            )
        lines = [f"blueprint of {node.label} ({node.place})"]
        for item in graph["nodes"]:
            outs = ", ".join(o["name"] for o in item.get("outs", []))
            ins = ", ".join(feeds.get(item["id"], []))
            line = f" line {item['line']}" if item.get("line") else ""
            lines.append(
                f"  {item['id']} {item['kind']} {titles[item['id']]}{line}"
                + (f"  inside {item['parent']}" if item.get("parent") else "")
                + (f"  in: {ins}" if ins else "")
                + (f"  out: {outs}" if outs else "")
            )
        steps = [f"{e['from']}-{e['fp']}->{e['to']}" for e in graph.get("exec", [])]
        if steps:
            lines.append("  order: " + ", ".join(steps))
        return {"node": brief(node), "graph": graph, "text": "\n".join(lines)}


def _relations(title: str, items: list[tuple[str, Counter[str]]]) -> list[str]:
    if not items:
        return [f"{title}: nothing"]
    lines = [f"{title}:"]
    for node_id, kinds in items[:25]:
        lines.append(
            f"  {node_id}  ({', '.join(f'{k} {n}' for k, n in kinds.most_common())})"
        )
    if len(items) > 25:
        lines.append(f"  … and {len(items) - 25} more")
    return lines


def _relation_json(node: Node, kinds: Counter[str]) -> dict[str, Any]:
    return {**brief(node), "kinds": dict(kinds)}


def _row_line(row: dict[str, Any]) -> str:
    relational = "-" if row["relational"] is None else f"{row['relational']:.2f}"
    split = ", ".join(f"{c['class']}({c['groups']})" for c in row["split_classes"])
    return f"{row['module']:<45}{row['members']:>7}{row['groups']:>7}{relational:>9}{row['ca']:>4}{row['ce']:>4}{row['instability']:>13.2f}  {split}"


def _pair_lines(pairs: list[dict[str, Any]], top: int) -> list[str]:
    lines = [f"most coupled module pairs (top {top}):"]
    for pair in pairs[:top]:
        arrow = "<->" if pair["cycle"] else "->"
        lines.append(
            f"  {pair['label']:<8} {pair['score']:>6g}  {pair['a']} {arrow} {pair['b']}  ({pair['kinds']})"
        )
    cycles = [p for p in pairs if p["cycle"]]
    return lines + [
        "",
        "module cycles: "
        + (", ".join(f"{p['a']} <-> {p['b']}" for p in cycles) or "none"),
    ]


def _oversized_lines(oversized: list[dict[str, Any]], top: int) -> list[str]:
    return [
        f"too large or complex: {len(oversized)} (largest {min(top, len(oversized))}):",
        *(
            f"  {item['kind']:<9}{item['label']}  {describe_size(item['kind'], item['size'])}"
            for item in oversized[:top]
        ),
    ]
