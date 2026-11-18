from dataclasses import dataclass
from typing import Any

from code_blueprints.analysis.diff.source import node_text
from code_blueprints.analysis.diff.status import ADDED, MODIFIED, REMOVED
from code_blueprints.analysis.project import Project
from code_blueprints.analysis.workspace.parsed import ParsedModule
from code_blueprints.analysis.diff.revisions import FileChange


class ChangeStatus:
    def __init__(self, base: Project, head: Project) -> None:
        self.base = base
        self.head = head
        self.status: dict[str, str] = {}
        self.removed: dict[str, dict[str, Any]] = {}

    def compare_file(self, change: FileChange) -> None:
        path = change.path
        base_path = change.old_path or path
        self.status[f"mod:{path}"] = change.status
        head_module = (
            self.head.workspace.module(path) if change.status != REMOVED else None
        )
        base_module = (
            self.base.workspace.module(base_path) if change.status != ADDED else None
        )
        head_summary = self.head.module_summary(path) if head_module else None
        base_summary = self.base.module_summary(base_path) if base_module else None
        if base_summary is not None:
            base_summary = {**base_summary, "path": path}
        removed_quals = self._compare_symbols(
            _symbols(base_module, path) if base_module else {},
            _symbols(head_module, path) if head_module else {},
        )
        self._compare_members(path, base_summary, head_summary)
        if change.status == REMOVED:
            self.removed[path] = {"module": base_summary}
        elif removed_quals or path in self.removed:
            self._record_removed(path, base_summary, set(removed_quals))

    def _compare_symbols(
        self, base: dict[str, "_Symbol"], head: dict[str, "_Symbol"]
    ) -> list[str]:
        for symbol_id, symbol in head.items():
            previous = base.get(symbol_id)
            if previous is None:
                self.status[symbol_id] = ADDED
            elif previous.text != symbol.text:
                self.status[symbol_id] = MODIFIED
        removed_ids = [symbol_id for symbol_id in base if symbol_id not in head]
        for symbol_id in removed_ids:
            self.status[symbol_id] = REMOVED
        return [base[symbol_id].qual for symbol_id in removed_ids]

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
        _record_removed_members(
            self.removed.setdefault(path, {}), path, base, set(removed)
        )

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


@dataclass(frozen=True)
class _Symbol:
    id: str
    qual: str
    text: str


def _symbols(module: ParsedModule, path: str) -> dict[str, _Symbol]:
    found: dict[str, _Symbol] = {}
    for qual, parsed_class in module.classes.items():
        found[f"cls:{path}:{qual}"] = _Symbol(
            f"cls:{path}:{qual}", qual, node_text(module, parsed_class.node)
        )
    for qual, function in module.functions.items():
        kind = "m" if function.class_qualname else "fn"
        found[f"{kind}:{path}:{qual}"] = _Symbol(
            f"{kind}:{path}:{qual}", qual, node_text(module, function.node)
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


def _record_removed_members(
    entry: dict[str, Any], path: str, base: dict[str, Any], removed: set[str]
) -> None:
    for symbol in base["symbols"]:
        for key in ("fields", "members"):
            gone = [
                member
                for member in symbol.get(key, [])
                if f"f:{path}:{symbol['qual']}.{member[0]}" in removed
            ]
            if gone:
                entry.setdefault(key, {})[symbol["qual"]] = gone
    constants = [
        constant
        for constant in base.get("constants", [])
        if f"c:{path}:{constant[0]}" in removed
    ]
    if constants:
        entry["constants"] = constants
