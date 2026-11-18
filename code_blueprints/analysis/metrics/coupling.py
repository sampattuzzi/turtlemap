from collections import Counter
from typing import Any

from code_blueprints.analysis.metrics.formulas import FORMULAS
from code_blueprints.analysis.metrics.code_graph import (
    Edge,
    Node,
    QueryError,
    TEST_PATH,
    brief,
    CodeGraph,
)

TIGHT_SCORE = 12.0

MODERATE_SCORE = 4.0

NARROW_SURFACE = 3


class Coupling:
    def __init__(self, code: CodeGraph) -> None:
        self._code = code

    def coupling(self, first: str, second: str) -> dict[str, Any]:
        a, b = self._code.resolve(first), self._code.resolve(second)
        a_ids, b_ids = self._code.subtree(a), self._code.subtree(b)
        if a_ids & b_ids:
            raise QueryError(
                f"{a.label} and {b.label} overlap; pick two separate parts."
            )
        forward = self._edges_between(a_ids, b_ids)
        backward = self._edges_between(b_ids, a_ids)
        score = sum(e.weight for e in forward + backward)
        tight = _tight_reasons(forward, backward, score)
        shared = self._shared_fields(a_ids, b_ids)
        verdict = _verdict(tight, score, forward + backward, shared)
        lines = [
            f"coupling between {a.label} and {b.label}: {verdict} (score {score:g})",
            *(f"  tight because {reason}" for reason in tight),
            *_direction(self._code, a, b, forward),
            *_direction(self._code, b, a, backward),
            *self._shared_lines(shared),
            f"formula: {FORMULAS['coupling']}",
        ]
        return {
            "a": brief(a),
            "b": brief(b),
            "label": verdict,
            "score": score,
            "a_to_b": _direction_json(forward),
            "b_to_a": _direction_json(backward),
            "cycle": bool(forward and backward),
            "shared_fields": {
                f: {"written": written} for f, (_, written) in sorted(shared.items())
            },
            "formula": FORMULAS["coupling"],
            "text": "\n".join(lines),
        }

    def _edges_between(
        self, sources: frozenset[str], targets: frozenset[str]
    ) -> list[Edge]:
        return [
            e
            for i in sources
            for e in self._code.outgoing.get(i, [])
            if e.target in targets
        ]

    def _shared_lines(self, shared: dict[str, tuple[bool, bool]]) -> list[str]:
        if not shared:
            return []
        return [
            "  both touch: "
            + ", ".join(
                f"{self._code.nodes[f].qual}{' (written)' if written else ''}"
                for f, (_, written) in sorted(shared.items())
            )
        ]

    def instability(self, module: Node, include_tests: bool = False) -> dict[str, Any]:
        mine = self._code.subtree(module)
        efferent = {
            self._code.module_of(e.target)
            for i in mine
            for e in self._code.outgoing.get(i, [])
            if e.target not in mine
        }
        afferent = {
            self._code.module_of(e.source)
            for i in mine
            for e in self._code.incoming.get(i, [])
            if e.source not in mine
        }
        efferent.discard(None)
        afferent.discard(None)
        if not include_tests:
            afferent = {
                m for m in afferent if m is not None and not TEST_PATH.search(m)
            }
        ca, ce = len(afferent), len(efferent)
        return {
            "ca": ca,
            "ce": ce,
            "instability": ce / (ca + ce) if ca + ce else 0.0,
        }

    def _shared_fields(
        self, a_ids: frozenset[str], b_ids: frozenset[str]
    ) -> dict[str, tuple[bool, bool]]:
        def touches(ids: frozenset[str]) -> dict[str, bool]:
            found: dict[str, bool] = {}
            for i in ids:
                for edge in self._code.outgoing.get(i, []):
                    if edge.target.startswith("f:") and edge.kinds & {
                        "reads",
                        "writes",
                    }:
                        if edge.target not in a_ids and edge.target not in b_ids:
                            found[edge.target] = (
                                found.get(edge.target, False) or "writes" in edge.kinds
                            )
            return found

        mine, theirs = touches(a_ids), touches(b_ids)
        return {f: (True, mine[f] or theirs[f]) for f in mine.keys() & theirs.keys()}

    def module_pairs(
        self, modules: list[Node], include_tests: bool
    ) -> list[dict[str, Any]]:
        weights = self._module_edges({m.path for m in modules})
        pairs = [
            _module_pair(a, b, weights.get((a, b), []), weights.get((b, a), []))
            for a, b in sorted({tuple(sorted(key)) for key in weights})
        ]
        return sorted(pairs, key=lambda p: (-float(p["score"]), str(p["a"])))

    def _module_edges(
        self, wanted: set[str | None]
    ) -> dict[tuple[str, str], list[Edge]]:
        weights: dict[tuple[str, str], list[Edge]] = {}
        for edge in self._code.edges:
            a, b = self._code.module_of(edge.source), self._code.module_of(edge.target)
            if a is None or b is None or a == b or a not in wanted or b not in wanted:
                continue
            weights.setdefault((a, b), []).append(edge)
        return weights


def _tight_reasons(
    forward: list[Edge], backward: list[Edge], score: float
) -> list[str]:
    both = forward + backward
    checks = (
        ("inheritance", any(e.kinds & {"inherits", "realizes"} for e in both)),
        ("writes the other's fields", any("writes" in e.kinds for e in both)),
        ("they depend on each other", bool(forward and backward)),
        (f"score {score:g} >= {TIGHT_SCORE:g}", score >= TIGHT_SCORE),
    )
    return [reason for reason, hit in checks if hit]


def _verdict(
    tight: list[str],
    score: float,
    edges: list[Edge],
    shared: dict[str, tuple[bool, bool]],
) -> str:
    if tight:
        return "tight"
    touched = len({e.target for e in edges})
    shared_writes = any(written for _, written in shared.values())
    if score >= MODERATE_SCORE or touched > NARROW_SURFACE or shared_writes:
        return "moderate"
    if edges or shared:
        return "loose"
    return "none"


def _module_pair(
    a: str, b: str, forward: list[Edge], backward: list[Edge]
) -> dict[str, Any]:
    score = sum(e.weight for e in forward + backward)
    kinds = Counter(k for e in forward + backward for k in sorted(e.kinds))
    leads = bool(forward or not backward)
    return {
        "a": a if leads else b,
        "b": b if leads else a,
        "score": score,
        "label": _pair_label(forward, backward, score),
        "cycle": bool(forward and backward),
        "kinds": ", ".join(f"{k} {n}" for k, n in kinds.most_common()),
    }


def _pair_label(forward: list[Edge], backward: list[Edge], score: float) -> str:
    both = forward + backward
    if (
        any(e.kinds & {"inherits", "realizes", "writes"} for e in both)
        or bool(forward and backward)
        or score >= TIGHT_SCORE
    ):
        return "tight"
    if score >= MODERATE_SCORE or len({e.target for e in both}) > NARROW_SURFACE:
        return "moderate"
    return "loose"


def _direction(code: CodeGraph, a: Node, b: Node, edges: list[Edge]) -> list[str]:
    if not edges:
        return [f"  {a.label} -> {b.label}: nothing"]
    kinds = Counter(k for e in edges for k in sorted(e.kinds))
    targets = sorted(
        {code.nodes[e.target].qual or code.nodes[e.target].name for e in edges}
    )
    sources = sorted(
        {code.nodes[e.source].qual or code.nodes[e.source].name for e in edges}
    )
    return [
        f"  {a.label} -> {b.label}: {len(edges)} edge(s), {', '.join(f'{k} {n}' for k, n in kinds.most_common())}",
        f"    touches {len(targets)} of its members: {', '.join(targets[:12])}{' …' if len(targets) > 12 else ''}",
        f"    from {len(sources)} member(s): {', '.join(sources[:12])}{' …' if len(sources) > 12 else ''}",
    ]


def _direction_json(edges: list[Edge]) -> dict[str, Any]:
    return {
        "edges": len(edges),
        "kinds": dict(Counter(k for e in edges for k in sorted(e.kinds))),
        "touched": sorted({e.target for e in edges}),
        "from": sorted({e.source for e in edges}),
    }
