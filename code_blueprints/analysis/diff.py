import ast
import difflib
import textwrap
from dataclasses import dataclass
from typing import Any, Callable

from code_blueprints.analysis.project import Project
from code_blueprints.analysis.workspace import ParsedModule
from code_blueprints.git import DiffRange, FileChange

ADDED = "added"
REMOVED = "removed"
MODIFIED = "modified"


@dataclass(frozen=True)
class _Symbol:
    id: str
    qual: str
    text: str


class ProjectDiff:
    def __init__(
        self,
        base: Project,
        head: Project,
        changes: list[FileChange],
        diff_range: DiffRange,
    ) -> None:
        self.base = base
        self.head = head
        self.range = diff_range
        self.changes = {change.path: change for change in changes}
        self.base_path_of = {
            change.path: change.old_path or change.path
            for change in changes
            if change.status != ADDED
        }
        self.status: dict[str, str] = {}
        self.removed: dict[str, dict[str, Any]] = {}
        for change in changes:
            self._compare_file(change)

    def summary(self) -> dict[str, Any]:
        counts = {ADDED: 0, REMOVED: 0, MODIFIED: 0}
        for change in self.changes.values():
            counts[change.status] += 1
        return {
            "spec": self.range.spec,
            "base": self.range.base,
            "head": self.range.head,
            "baseLabel": self.range.base_label,
            "headLabel": self.range.head_label,
            "files": {
                path: {
                    "status": change.status,
                    **({"oldPath": change.old_path} if change.old_path else {}),
                }
                for path, change in sorted(self.changes.items())
            },
            "counts": counts,
            "status": self.status,
            "removed": self.removed,
        }

    def outline(self, path: str) -> list[dict[str, Any]] | None:
        change = self.changes.get(path)
        head = self.head.outline(path)
        if change is None:
            return head
        if change.status == REMOVED:
            return _mark_all(self.base.outline(self.base_path_of[path]) or [], REMOVED)
        if change.status == ADDED:
            return _mark_all(head or [], ADDED)
        base = self.base.outline(self.base_path_of[path]) or []
        return self._merge_outline(path, base, head or [], None)

    def function(self, path: str, qual: str) -> dict[str, Any] | None:
        change = self.changes.get(path)
        head = self.head.function(path, qual)
        if change is None:
            return head
        base_path = self.base_path_of.get(path)
        base = self.base.function(base_path, qual) if base_path else None
        if head is None and base is None:
            return None
        if head is None:
            assert base is not None
            return {
                **base,
                "path": path,
                "code": [[no, text, REMOVED] for no, text in base["code"]],
                "graph": _mark_graph(base["graph"], REMOVED),
            }
        if base is None:
            return {
                **head,
                "code": [[no, text, ADDED] for no, text in head["code"]],
                "graph": _mark_graph(head["graph"], ADDED),
            }
        if _function_text(self.base, base_path or path, qual) == _function_text(
            self.head, path, qual
        ):
            return head
        return {
            **head,
            "code": _merge_code(base["code"], head["code"]),
            "graph": merge_graphs(base["graph"], head["graph"]),
        }

    def _compare_file(self, change: FileChange) -> None:
        path = change.path
        base_path = change.old_path or path
        self.status[f"mod:{path}"] = change.status
        head_module = (
            self.head.workspace.module(path) if change.status != REMOVED else None
        )
        base_module = (
            self.base.workspace.module(base_path) if change.status != ADDED else None
        )
        head_symbols = _symbols(head_module, path) if head_module else {}
        base_symbols = _symbols(base_module, path) if base_module else {}
        head_summary = self.head.module_summary(path) if head_module else None
        base_summary = self.base.module_summary(base_path) if base_module else None
        if base_summary is not None:
            base_summary = {**base_summary, "path": path}
        for symbol_id, symbol in head_symbols.items():
            previous = base_symbols.get(symbol_id)
            if previous is None:
                self.status[symbol_id] = ADDED
            elif previous.text != symbol.text:
                self.status[symbol_id] = MODIFIED
        removed_ids = [
            symbol_id for symbol_id in base_symbols if symbol_id not in head_symbols
        ]
        for symbol_id in removed_ids:
            self.status[symbol_id] = REMOVED
        self._compare_members(path, base_summary, head_summary)
        if change.status == REMOVED:
            self.removed[path] = {"module": base_summary}
        elif removed_ids or path in self.removed:
            self._record_removed(
                path, base_summary, {base_symbols[i].qual for i in removed_ids}
            )

    def _compare_members(
        self, path: str, base: dict[str, Any] | None, head: dict[str, Any] | None
    ) -> None:
        base_members = _members(base, path)
        head_members = _members(head, path)
        for member_id, value in head_members.items():
            if member_id not in base_members:
                self.status[member_id] = ADDED
            elif base_members[member_id] != value:
                self.status[member_id] = MODIFIED
        removed = [
            member_id for member_id in base_members if member_id not in head_members
        ]
        if not removed or base is None:
            return
        for member_id in removed:
            self.status[member_id] = REMOVED
        entry = self.removed.setdefault(path, {})
        for symbol in base["symbols"]:
            fields = [
                field
                for field in symbol.get("fields", [])
                if f"f:{path}:{symbol['qual']}.{field[0]}" in removed
            ]
            members = [
                member
                for member in symbol.get("members", [])
                if f"f:{path}:{symbol['qual']}.{member[0]}" in removed
            ]
            if fields:
                entry.setdefault("fields", {})[symbol["qual"]] = fields
            if members:
                entry.setdefault("members", {})[symbol["qual"]] = members
        constants = [
            constant
            for constant in base.get("constants", [])
            if f"c:{path}:{constant[0]}" in removed
        ]
        if constants:
            entry["constants"] = constants

    def _record_removed(
        self, path: str, base: dict[str, Any] | None, removed_quals: set[str]
    ) -> None:
        if base is None:
            return
        entry = self.removed.setdefault(path, {})
        symbols = [
            symbol for symbol in base["symbols"] if symbol["qual"] in removed_quals
        ]
        if symbols:
            entry["symbols"] = symbols
        methods: dict[str, list[dict[str, Any]]] = {}
        for symbol in base["symbols"]:
            if symbol["qual"] in removed_quals:
                continue
            gone = [
                method
                for method in symbol.get("methods", [])
                if method["qual"] in removed_quals
            ]
            if gone:
                methods[symbol["qual"]] = gone
        if methods:
            entry["methods"] = methods

    def _merge_outline(
        self,
        path: str,
        base: list[dict[str, Any]],
        head: list[dict[str, Any]],
        owner: str | None,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        matcher = difflib.SequenceMatcher(
            None,
            [_outline_key(item) for item in base],
            [_outline_key(item) for item in head],
            autojunk=False,
        )
        for tag, b0, b1, h0, h1 in matcher.get_opcodes():
            if tag == "equal":
                for old, new in zip(base[b0:b1], head[h0:h1]):
                    merged.append(self._merge_item(path, old, new, owner))
                continue
            merged += [_mark_item(item, REMOVED) for item in base[b0:b1]]
            merged += [_mark_item(item, ADDED) for item in head[h0:h1]]
        return merged

    def _merge_item(
        self, path: str, old: dict[str, Any], new: dict[str, Any], owner: str | None
    ) -> dict[str, Any]:
        qual = f"{owner}.{new['name']}" if owner and "name" in new else new.get("name")
        if new["kind"] == "class":
            status = self.status.get(f"cls:{path}:{qual}")
            body = self._merge_outline(
                path, old.get("body", []), new.get("body", []), qual
            )
            return {**new, "body": body, **({"diff": status} if status else {})}
        if new["kind"] == "def":
            status = self.status.get(f"{'m' if owner else 'fn'}:{path}:{qual}")
            return {**new, "diff": status} if status else new
        if new["kind"] == "imports" and old.get("count") != new.get("count"):
            return {**new, "diff": MODIFIED}
        return new


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


def _mark_graph(graph: dict[str, Any], status: str) -> dict[str, Any]:
    return {**graph, "nodes": [{**node, "diff": status} for node in graph["nodes"]]}


def _node_key(node: dict[str, Any]) -> tuple[str, str]:
    return (node["kind"], node.get("title", ""))


def _node_signature(node: dict[str, Any]) -> tuple[Any, ...]:
    return (
        tuple((pin["name"], pin.get("lit")) for pin in node.get("ins", [])),
        tuple(pin["name"] for pin in node.get("outs", [])),
        node.get("note"),
    )


def _merge_code(base: list[list[Any]], head: list[list[Any]]) -> list[list[Any]]:
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


def _outline_key(item: dict[str, Any]) -> tuple[str, str]:
    if item["kind"] in ("def", "class"):
        return (item["kind"], item["name"])
    if item["kind"] == "imports":
        return ("imports", "")
    return (item["kind"], item["text"].strip())


def _mark_item(item: dict[str, Any], status: str) -> dict[str, Any]:
    marked = {**item, "diff": status}
    if "body" in item:
        marked["body"] = [_mark_item(child, status) for child in item["body"]]
    return marked


def _mark_all(items: list[dict[str, Any]], status: str) -> list[dict[str, Any]]:
    return [_mark_item(item, status) for item in items]


def _symbols(module: ParsedModule, path: str) -> dict[str, _Symbol]:
    found: dict[str, _Symbol] = {}
    for qual, parsed_class in module.classes.items():
        found[f"cls:{path}:{qual}"] = _Symbol(
            f"cls:{path}:{qual}", qual, _node_text(module, parsed_class.node)
        )
    for qual, function in module.functions.items():
        kind = "m" if function.class_qualname else "fn"
        found[f"{kind}:{path}:{qual}"] = _Symbol(
            f"{kind}:{path}:{qual}", qual, _node_text(module, function.node)
        )
    return found


def _members(summary: dict[str, Any] | None, path: str) -> dict[str, str]:
    if summary is None:
        return {}
    members: dict[str, str] = {}
    for symbol in summary["symbols"]:
        for name, pin in symbol.get("fields", []):
            members[f"f:{path}:{symbol['qual']}.{name}"] = pin["label"]
        for name, value in symbol.get("members", []):
            members[f"f:{path}:{symbol['qual']}.{name}"] = str(value)
    for constant in summary.get("constants", []):
        members[f"c:{path}:{constant[0]}"] = f"{constant[1]['label']}={constant[2]}"
    return members


def _function_text(project: Project, path: str, qual: str) -> str | None:
    module = project.workspace.module(path)
    if module is None or qual not in module.functions:
        return None
    return _node_text(module, module.functions[qual].node)


def _node_text(
    module: ParsedModule, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
) -> str:
    start = min([node.lineno] + [decorator.lineno for decorator in node.decorator_list])
    end = node.end_lineno or node.lineno
    return textwrap.dedent(
        "\n".join(line.rstrip() for line in module.lines[start - 1 : end])
    )
