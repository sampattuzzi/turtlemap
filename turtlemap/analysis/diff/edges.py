from collections.abc import Iterable, Mapping
from typing import Any

from turtlemap.analysis.dependencies import edge_table, shown_kinds
from turtlemap.analysis.diff.status import ADDED, MODIFIED, REMOVED

Edge = list[Any]


def compare_edges(
    base: Iterable[Edge], head: Iterable[Edge], renamed: Mapping[str, str]
) -> dict[str, Any]:
    before = {
        (edge[0], edge[1]): edge for edge in (_moved_edge(e, renamed) for e in base)
    }
    after = {(edge[0], edge[1]): edge for edge in head}
    status = [
        [source, target, change]
        for (source, target), edge in after.items()
        if (change := _change(before.get((source, target)), edge))
    ]
    removed = [edge for key, edge in before.items() if key not in after]
    status.extend([edge[0], edge[1], REMOVED] for edge in removed)
    return {"status": sorted(status), "removed": edge_table(removed)}


def _change(previous: Edge | None, edge: Edge) -> str | None:
    if previous is None:
        return ADDED
    return MODIFIED if _looks(previous) != _looks(edge) else None


def _looks(edge: Edge) -> tuple[frozenset[str], frozenset[str]]:
    return shown_kinds(edge[2]), frozenset(edge[3])


def _moved_edge(edge: Edge, renamed: Mapping[str, str]) -> Edge:
    return [_moved(edge[0], renamed), _moved(edge[1], renamed), edge[2], edge[3]]


def _moved(node_id: str, renamed: Mapping[str, str]) -> str:
    kind, _, rest = node_id.partition(":")
    for old, new in renamed.items():
        if rest == old or rest.startswith(f"{old}:"):
            return f"{kind}:{new}{rest[len(old):]}"
    return node_id
