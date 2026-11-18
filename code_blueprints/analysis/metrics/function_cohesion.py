from typing import Any

from code_blueprints.analysis.metrics.code_graph import (
    FunctionGraph,
    Node,
    QueryError,
    brief,
)
from code_blueprints.analysis.metrics.formulas import FORMULAS
from code_blueprints.analysis.metrics.groups import cohesion_label, connected_groups

RECEIVERS = frozenset({"self", "cls", "this"})


class FunctionCohesion:
    def __init__(self, function_graph: FunctionGraph | None) -> None:
        self._function_graph = function_graph

    def measure(self, node: Node) -> dict[str, Any]:
        graph = self.graph(node)
        items = {n["id"]: n for n in graph["nodes"]}
        wired = _data_wires(graph, items)
        joined = {i: links for i, links in wired.items() if links}
        strands = connected_groups({i: set() for i in joined}, joined, set())
        lone = [
            i
            for i, links in wired.items()
            if not links and items[i]["kind"] != "return"
        ]
        verdict = cohesion_label(len(strands)) if strands else "n/a"
        return {
            "node": brief(node),
            "groups": len(strands),
            "strands": [_titles(items, g) for g in strands],
            "unwired": [node_title(items[i]) for i in lone],
            "label": verdict,
            "formula": FORMULAS["function"],
            "text": "\n".join(_lines(node, items, strands, lone, verdict)),
        }

    def graph(self, node: Node) -> dict[str, Any]:
        if (
            node.kind not in ("function", "method")
            or node.path is None
            or node.qual is None
        ):
            raise QueryError(
                f"{node.label} is a {node.kind}; blueprints exist for functions and methods."
            )
        if self._function_graph is None:
            raise QueryError("Function blueprints are not available here.")
        data = self._function_graph(node.path, node.qual)
        if data is None:
            raise QueryError(f"Could not read {node.label}.")
        graph: dict[str, Any] = data["graph"]
        return graph


def _data_wires(
    graph: dict[str, Any], items: dict[str, dict[str, Any]]
) -> dict[str, set[str]]:
    skipped = _parameter_nodes(graph, items)
    wired: dict[str, set[str]] = {i: set() for i in items if i not in skipped}
    for edge in graph["edges"]:
        if edge["from"] in wired and edge["to"] in wired:
            wired[edge["from"]].add(edge["to"])
            wired[edge["to"]].add(edge["from"])
    return wired


def _parameter_nodes(
    graph: dict[str, Any], items: dict[str, dict[str, Any]]
) -> set[str]:
    entry = next((i for i, n in items.items() if n["kind"] == "entry"), None)
    if entry is None:
        return set()
    unpacked = {
        e["to"]
        for e in graph["edges"]
        if e["from"] == entry
        and e["fp"] in RECEIVERS
        and items[e["to"]]["kind"] == "break"
    }
    return unpacked | {entry}


def _lines(
    node: Node,
    items: dict[str, dict[str, Any]],
    strands: list[list[str]],
    lone: list[str],
    verdict: str,
) -> list[str]:
    lines = [
        f"{node.kind} {node.label}: {len(strands)} independent dataflow strand(s), {verdict} cohesion"
    ]
    if len(strands) > 1:
        lines += [
            f"  strand {n}: {', '.join(_titles(items, g))}"
            for n, g in enumerate(strands, 1)
        ]
    if lone:
        lines.append(f"  steps with no data wires: {', '.join(_titles(items, lone))}")
    lines.append(f"formula: {FORMULAS['function']}")
    return lines


def _titles(items: dict[str, dict[str, Any]], ids: list[str]) -> list[str]:
    return [node_title(items[i]) for i in sorted(ids, key=_order)]


def node_title(item: dict[str, Any]) -> str:
    title = str(item.get("title", item["kind"]))
    if item.get("expr"):
        title += " [" + " ".join(str(line).strip() for line in item["expr"]) + "]"
    if item.get("code"):
        title += f" [{item['code']}]"
    return title


def _order(node_id: str) -> int:
    digits = "".join(ch for ch in node_id if ch.isdigit())
    return int(digits) if digits else 0
