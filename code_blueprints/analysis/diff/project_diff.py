from typing import Any

from code_blueprints.analysis.diff.changes import ChangeStatus
from code_blueprints.analysis.diff.merge import mark_graph, merge_code, merge_graphs
from code_blueprints.analysis.diff.outline import OutlineMerge, mark_all
from code_blueprints.analysis.diff.source import function_text
from code_blueprints.analysis.diff.status import ADDED, MODIFIED, REMOVED
from code_blueprints.analysis.diff.units import ReviewUnit, review_units
from code_blueprints.analysis.project import Project
from code_blueprints.analysis.diff.revisions import DiffRange, FileChange


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
        compared = ChangeStatus(base, head)
        self.status = compared.status
        self.removed = compared.removed
        self.units: dict[str, list[ReviewUnit]] = {}
        for change in changes:
            compared.compare_file(change)
            self.units[change.path] = review_units(base, head, change)

    def fingerprints(self, unit_ids: list[str]) -> list[str]:
        wanted = set(unit_ids)
        return [
            unit.fingerprint
            for units in self.units.values()
            for unit in units
            if unit.id in wanted
        ]

    def seen_units(self, seen_fingerprints: set[str]) -> list[str]:
        return [
            unit.id
            for units in self.units.values()
            for unit in units
            if unit.fingerprint in seen_fingerprints
        ]

    def summary(self) -> dict[str, Any]:
        counts = {ADDED: 0, REMOVED: 0, MODIFIED: 0}
        for change in self.changes.values():
            counts[change.status] += 1
        return {
            "spec": self.range.spec,
            "baseSha": self.range.base_sha,
            "headSha": self.range.head_sha,
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
            "units": {
                path: [unit.to_json() for unit in units]
                for path, units in sorted(self.units.items())
            },
        }

    def outline(self, path: str) -> list[dict[str, Any]] | None:
        change = self.changes.get(path)
        head = self.head.outline(path)
        if change is None:
            return head
        if change.status == REMOVED:
            return mark_all(self.base.outline(self.base_path_of[path]) or [], REMOVED)
        if change.status == ADDED:
            return mark_all(head or [], ADDED)
        base = self.base.outline(self.base_path_of[path]) or []
        return OutlineMerge(path, self.status).merge(base, head or [], None)

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
                "graph": mark_graph(base["graph"], REMOVED),
            }
        if base is None:
            return {
                **head,
                "code": [[no, text, ADDED] for no, text in head["code"]],
                "graph": mark_graph(head["graph"], ADDED),
            }
        if function_text(self.base, base_path or path, qual) == function_text(
            self.head, path, qual
        ):
            return head
        return {
            **head,
            "code": merge_code(base["code"], head["code"]),
            "graph": merge_graphs(base["graph"], head["graph"]),
        }
