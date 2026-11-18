import difflib
from collections.abc import Callable
from typing import Any

from code_blueprints.analysis.diff.status import ADDED, MODIFIED, REMOVED


def merge_graphs(base: dict[str, Any], head: dict[str, Any]) -> dict[str, Any]:
    base_nodes = base["nodes"]
    head_nodes = [dict(node) for node in head["nodes"]]
    matcher = difflib.SequenceMatcher(
        None,
        [_node_key(node) for node in base_nodes],
        [_node_key(node) for node in head_nodes],
        autojunk=False,
    )
    to_head: dict[str, str] = {}
    matched_head: set[str] = set()
    removed_nodes: list[dict[str, Any]] = []
    for tag, b0, b1, h0, h1 in matcher.get_opcodes():
        if tag == "equal":
            for old, new in zip(base_nodes[b0:b1], head_nodes[h0:h1]):
                to_head[old["id"]] = new["id"]
                matched_head.add(new["id"])
                if _node_signature(old) != _node_signature(new):
                    new["diff"] = MODIFIED
            continue
        for old in base_nodes[b0:b1]:
            removed_nodes.append(
                {
                    **old,
                    "id": f"base:{old['id']}",
                    "diff": REMOVED,
                    "baseLine": old.get("line"),
                }
            )
    for node in head_nodes:
        if node["id"] not in matched_head:
            node["diff"] = ADDED
    by_id = {node["id"]: node for node in head_nodes + removed_nodes}

    def mapped(node_id: str) -> str:
        return to_head.get(node_id, f"base:{node_id}")

    edges = _merge_wires(base["edges"], head["edges"], mapped, by_id, data=True)
    execs = _merge_wires(base["exec"], head["exec"], mapped, by_id, data=False)
    merged: dict[str, Any] = {
        "nodes": head_nodes + removed_nodes,
        "edges": edges,
        "exec": execs,
    }
    if base.get("truncated") or head.get("truncated"):
        merged["truncated"] = True
    return merged


def _merge_wires(
    base: list[dict[str, Any]],
    head: list[dict[str, Any]],
    mapped: Callable[[str], str],
    nodes: dict[str, dict[str, Any]],
    *,
    data: bool,
) -> list[dict[str, Any]]:
    key = (
        (lambda edge: (edge["from"], edge["fp"], edge["to"], edge.get("tp")))
        if data
        else (lambda edge: (edge["from"], edge["fp"], edge["to"]))
    )
    old = [
        {**edge, "from": mapped(edge["from"]), "to": mapped(edge["to"])}
        for edge in base
    ]
    old_keys = {key(edge) for edge in old}
    head_keys = {key(edge) for edge in head}
    merged = [
        edge if key(edge) in old_keys else {**edge, "diff": ADDED} for edge in head
    ]
    for edge in old:
        if key(edge) in head_keys:
            continue
        source, target = nodes.get(edge["from"]), nodes.get(edge["to"])
        if source is None or target is None:
            continue
        if data:
            _ensure_pin(source, "outs", edge["fp"])
            _ensure_pin(target, "ins", edge["tp"])
        else:
            target["execIn"] = True
            if edge["fp"] == "then":
                source["execOut"] = True
            elif edge["fp"] not in source.get("execOuts", []):
                source["execOuts"] = [*source.get("execOuts", []), edge["fp"]]
        merged.append({**edge, "diff": REMOVED})
    return merged


def _ensure_pin(node: dict[str, Any], side: str, name: str) -> None:
    pins = node.setdefault(side, [])
    if not any(pin["name"] == name for pin in pins):
        node[side] = [
            *pins,
            {"name": name, "type": {"label": "Any", "cat": "any"}, "diff": REMOVED},
        ]


def mark_graph(graph: dict[str, Any], status: str) -> dict[str, Any]:
    return {**graph, "nodes": [{**node, "diff": status} for node in graph["nodes"]]}


def _node_key(node: dict[str, Any]) -> tuple[str, str]:
    return (node["kind"], node.get("title", ""))


def _node_signature(node: dict[str, Any]) -> tuple[Any, ...]:
    return (
        tuple((pin["name"], pin.get("lit")) for pin in node.get("ins", [])),
        tuple(pin["name"] for pin in node.get("outs", [])),
        node.get("note"),
        node.get("code"),
        tuple(node.get("expr", [])),
    )


def merge_code(base: list[list[Any]], head: list[list[Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    matcher = difflib.SequenceMatcher(
        None,
        [text.strip() for _, text in base],
        [text.strip() for _, text in head],
        autojunk=False,
    )
    for tag, b0, b1, h0, h1 in matcher.get_opcodes():
        if tag == "equal":
            rows += [[no, text] for no, text in head[h0:h1]]
            continue
        rows += [[no, text, REMOVED] for no, text in base[b0:b1]]
        rows += [[no, text, ADDED] for no, text in head[h0:h1]]
    return rows
