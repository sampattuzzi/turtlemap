import difflib
from typing import Any

from code_blueprints.analysis.diff.status import ADDED, MODIFIED, REMOVED


class OutlineMerge:
    def __init__(self, path: str, status: dict[str, str]) -> None:
        self.path = path
        self.status = status

    def merge(
        self,
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
                    merged.append(self._item(old, new, owner))
                continue
            merged += [_mark_item(item, REMOVED) for item in base[b0:b1]]
            merged += [_mark_item(item, ADDED) for item in head[h0:h1]]
        return merged

    def _item(
        self, old: dict[str, Any], new: dict[str, Any], owner: str | None
    ) -> dict[str, Any]:
        qual = f"{owner}.{new['name']}" if owner and "name" in new else new.get("name")
        if new["kind"] == "class":
            status = self.status.get(f"cls:{self.path}:{qual}")
            body = self.merge(old.get("body", []), new.get("body", []), qual)
            return {**new, "body": body, **({"diff": status} if status else {})}
        if new["kind"] == "def":
            status = self.status.get(f"{'m' if owner else 'fn'}:{self.path}:{qual}")
            return {**new, "diff": status} if status else new
        if new["kind"] == "imports" and old.get("count") != new.get("count"):
            return {**new, "diff": MODIFIED}
        return new


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


def mark_all(items: list[dict[str, Any]], status: str) -> list[dict[str, Any]]:
    return [_mark_item(item, status) for item in items]
