from typing import Any

from turtlemap.analysis.metrics.code_graph import TEST_PATH, CodeGraph, Node

LIMITS: dict[str, dict[str, int]] = {
    "package": {"members": 15, "lines": 6000},
    "module": {"lines": 500, "members": 40},
    "class": {"lines": 300, "methods": 20},
    "function": {"lines": 50, "complexity": 15},
    "method": {"lines": 50, "complexity": 15},
}
SIZE_FORMULA = (
    "Size: a folder is too large past 15 files and folders directly inside it or "
    "6000 lines in those files; a file past 500 lines or 40 classes and functions; "
    "a class past 300 lines or 20 methods; a function or method past 50 lines or a "
    "complexity of 15 (1 + its branches, loops, handlers, cases, conditional "
    "expressions and extra and/or operands, counting the functions nested inside it)."
)
_MEMBER_KINDS = frozenset({"class", "function"})
_FOLDER_KINDS = frozenset({"package", "module"})


class Sizes:
    def __init__(self, code: CodeGraph) -> None:
        self._code = code

    def of(self, node: Node) -> dict[str, int]:
        if node.kind == "package":
            return {
                "members": sum(1 for c in node.children if c.kind in _FOLDER_KINDS),
                "lines": sum(c.lines or 0 for c in node.children if c.kind == "module"),
            }
        if node.kind == "module":
            return {
                "lines": node.lines or 0,
                "members": sum(1 for c in node.children if c.kind in _MEMBER_KINDS),
            }
        if node.kind == "class":
            return {
                "lines": _span(node),
                "methods": sum(1 for c in node.children if c.kind == "method"),
            }
        if node.kind in ("function", "method"):
            return {"lines": _span(node), "complexity": node.complexity or 1}
        return {}

    def oversized(self, include_tests: bool = False) -> list[dict[str, Any]]:
        found = []
        for node in self._code.nodes.values():
            limits = LIMITS.get(node.kind)
            if limits is None or (not include_tests and _is_test(node)):
                continue
            size = self.of(node)
            over = {
                measure: size[measure] / limit
                for measure, limit in limits.items()
                if size.get(measure, 0) > limit
            }
            if over:
                found.append(
                    {
                        "id": node.id,
                        "kind": node.kind,
                        "label": node.label,
                        "size": size,
                        "over": sorted(over),
                        "excess": max(over.values()),
                    }
                )
        found.sort(key=_rank)
        return found


def describe_size(kind: str, size: dict[str, int]) -> str:
    limits = LIMITS.get(kind, {})
    parts = []
    for measure, value in size.items():
        limit = limits.get(measure)
        flag = f" (limit {limit})" if limit is not None and value > limit else ""
        parts.append(f"{value} {measure}{flag}")
    return ", ".join(parts)


def _rank(item: dict[str, Any]) -> tuple[float, str]:
    return -float(item["excess"]), str(item["label"])


def _span(node: Node) -> int:
    if node.line is None or node.end is None:
        return 0
    return node.end - node.line + 1


def _is_test(node: Node) -> bool:
    if node.path is not None:
        return bool(TEST_PATH.search(node.path))
    return bool(TEST_PATH.search(node.id.partition(":")[2] + "/"))
