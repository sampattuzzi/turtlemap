import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from code_blueprints.languages.registry import EXTENSIONS

FunctionGraph = Callable[[str, str], dict[str, Any] | None]

KIND_WEIGHTS = {
    "inherits": 4.0,
    "realizes": 3.0,
    "writes": 3.0,
    "reads": 2.0,
    "creates": 1.0,
    "calls": 1.0,
    "has": 1.0,
    "uses": 0.5,
}
TIGHT_SCORE = 12.0
MODERATE_SCORE = 4.0
NARROW_SURFACE = 3
HUB_SHARE = 0.5
CONSTRUCTORS = frozenset({"__init__", "__post_init__", "__new__", "constructor"})
TEST_PATH = re.compile(
    r"(^|/)(tests?|testing|__tests__)/|(^|/)test_[^/]*\.py$|_test\.py$"
    r"|\.(test|spec)\.[cm]?[jt]sx?$"
)
MEMBER_KINDS = frozenset({"class", "function"})
CODE_KINDS = frozenset(
    {"package", "module", "class", "function", "method", "field", "constant"}
)
FORMULAS = {
    "class": "LCOM4: methods (constructors left out) are linked when they share a field of the class or call each other; the count of linked groups is the score, 1 is cohesive.",
    "module": "Linked groups among the module's classes and functions: two are linked when one uses the other or both touch the same module constant (constants link members but are not members themselves), plus relational cohesion = internal links / (internal + links to other project modules).",
    "package": "Linked groups among the package's modules, plus relational cohesion = links inside the package / (inside + links to the rest of the project).",
    "function": "Independent dataflow strands: nodes joined by data wires, leaving out the parameters and the unpacking of self, so two strands share no value. Heuristic.",
    "coupling": "Edges between the two, each weighted by kind (inherits 4, realizes 3, writes 3, reads 2, creates/calls/has 1, uses 0.5), plus fields of a third party that both touch. Tight: inheritance, writing the other's fields, a cycle, or score >= 12. Moderate: score >= 4, more than 3 distinct members touched, or a shared field that either writes. Otherwise loose.",
    "instability": "Instability = Ce / (Ca + Ce): Ca counts the project modules that depend on this one (tests left out), Ce the project modules it depends on.",
}


class QueryError(Exception):
    pass


@dataclass(eq=False)
class Node:
    id: str
    kind: str
    name: str
    parent: "Node | None"
    path: str | None = None
    qual: str | None = None
    line: int | None = None
    end: int | None = None
    children: list["Node"] = field(default_factory=list)

    @property
    def place(self) -> str:
        if self.path is None:
            return self.name
        span = f":{self.line}-{self.end}" if self.line and self.end else ""
        return f"{self.path}{span}"

    @property
    def label(self) -> str:
        if self.kind == "package":
            return f"{self.id.partition(':')[2]}/"
        if self.kind == "module":
            return self.path or self.name
        if self.qual is not None and self.path is not None:
            return f"{self.path} › {self.qual}"
        return self.name


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kinds: frozenset[str]
    labels: tuple[str, ...]

    @property
    def weight(self) -> float:
        return sum(KIND_WEIGHTS.get(kind, 0.0) for kind in self.kinds)


class Structure:
    def __init__(
        self, overview: dict[str, Any], function_graph: FunctionGraph | None = None
    ) -> None:
        self.root = Node("root", "root", str(overview.get("name", "project")), None)
        self.nodes: dict[str, Node] = {"root": self.root}
        self.imports: dict[str, set[str]] = {}
        self._function_graph = function_graph
        self._subtrees: dict[str, frozenset[str]] = {}
        for module in sorted(overview.get("modules", []), key=lambda m: m["path"]):
            self._add_module(module)
        for library in overview.get("libraries", []):
            self._add_library(library)
        self.edges = self._edges(overview.get("edges", {"ids": [], "rows": []}))
        self.outgoing: dict[str, list[Edge]] = {}
        self.incoming: dict[str, list[Edge]] = {}
        for edge in self.edges:
            self.outgoing.setdefault(edge.source, []).append(edge)
            self.incoming.setdefault(edge.target, []).append(edge)

    def resolve(self, name: str) -> Node:
        wanted = name.strip().rstrip("/")
        if wanted in self.nodes:
            return self.nodes[wanted]
        candidates = self._candidates(wanted)
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise QueryError(
                f"Nothing called {name!r}. Try find, or give an id such as mod:path/to/file.py or cls:path/to/file.py:ClassName."
            )
        shown = "\n".join(f"  {node.id}" for node in candidates[:12])
        raise QueryError(
            f"{name!r} could mean several things; give one of these ids:\n{shown}"
        )

    def find(self, text: str, limit: int = 30) -> dict[str, Any]:
        needle = text.lower()
        found = [
            node
            for node in self.nodes.values()
            if node.kind in CODE_KINDS
            and (needle in node.name.lower() or needle in node.id.lower())
        ]
        found.sort(key=lambda n: (n.name.lower() != needle, len(n.id)))
        lines = [f"{node.id}  ({node.kind}, {node.place})" for node in found[:limit]]
        if len(found) > limit:
            lines.append(f"… and {len(found) - limit} more")
        return {
            "matches": [_brief(node) for node in found[:limit]],
            "text": "\n".join(lines) or f"Nothing matches {text!r}.",
        }

    def tree(self, name: str | None = None, depth: int = 2) -> dict[str, Any]:
        start = self.resolve(name) if name else self.root
        lines: list[str] = []

        def walk(node: Node, level: int) -> None:
            for child in node.children:
                if child.kind in ("library", "libmodule", "name") and node is self.root:
                    continue
                count = f" ({_count(child)})" if child.children else ""
                lines.append(
                    f"{'  ' * level}{child.kind} {child.name}{count}  [{child.id}]"
                )
                if level + 1 < depth:
                    walk(child, level + 1)

        walk(start, 0)
        return {"node": _brief(start), "text": "\n".join(lines) or "(empty)"}

    def describe(self, name: str) -> dict[str, Any]:
        node = self.resolve(name)
        inside = self.subtree(node)
        level = "module" if node.kind in ("package", "module", "root") else "symbol"
        uses = self._lift(
            (
                e
                for i in inside
                for e in self.outgoing.get(i, [])
                if e.target not in inside
            ),
            lambda e: e.target,
            level,
        )
        used_by = self._lift(
            (
                e
                for i in inside
                for e in self.incoming.get(i, [])
                if e.source not in inside
            ),
            lambda e: e.source,
            level,
        )
        lines = [f"{node.kind} {node.label} ({node.place})"]
        if node.children:
            lines.append(f"contains {_count(node)}")
        lines += _relations("depends on", uses) + _relations("used by", used_by)
        if node.kind == "module" and node.path:
            silent = sorted(
                path
                for path in self.imports.get(node.path, set())
                if f"mod:{path}" not in {u for u, _ in uses}
            )
            if silent:
                lines.append(
                    "imports without a recorded use (re-exports or types only): "
                    + ", ".join(silent)
                )
        return {
            "node": _brief(node),
            "depends_on": [_relation_json(self.nodes[i], c) for i, c in uses],
            "used_by": [_relation_json(self.nodes[i], c) for i, c in used_by],
            "text": "\n".join(lines),
        }

    def cohesion(self, name: str) -> dict[str, Any]:
        node = self.resolve(name)
        if node.kind == "class":
            return self._class_cohesion(node)
        if node.kind in ("module", "package"):
            return self._group_cohesion(node)
        if node.kind in ("function", "method"):
            return self._function_cohesion(node)
        raise QueryError(
            f"Cohesion is measured for packages, modules, classes and functions, not a {node.kind}."
        )

    def coupling(self, first: str, second: str) -> dict[str, Any]:
        a, b = self.resolve(first), self.resolve(second)
        a_ids, b_ids = self.subtree(a), self.subtree(b)
        if a_ids & b_ids:
            raise QueryError(
                f"{a.label} and {b.label} overlap; pick two separate parts."
            )
        forward = [
            e for i in a_ids for e in self.outgoing.get(i, []) if e.target in b_ids
        ]
        backward = [
            e for i in b_ids for e in self.outgoing.get(i, []) if e.target in a_ids
        ]
        score = sum(e.weight for e in forward + backward)
        tight = [
            reason
            for reason, hit in (
                (
                    "inheritance",
                    any(e.kinds & {"inherits", "realizes"} for e in forward + backward),
                ),
                (
                    "writes the other's fields",
                    any("writes" in e.kinds for e in forward + backward),
                ),
                ("they depend on each other", bool(forward and backward)),
                (f"score {score:g} >= {TIGHT_SCORE:g}", score >= TIGHT_SCORE),
            )
            if hit
        ]
        touched = len({e.target for e in forward} | {e.target for e in backward})
        shared = self._shared_fields(a_ids, b_ids)
        shared_writes = any(written for _, written in shared.values())
        if tight:
            verdict = "tight"
        elif score >= MODERATE_SCORE or touched > NARROW_SURFACE or shared_writes:
            verdict = "moderate"
        elif forward or backward or shared:
            verdict = "loose"
        else:
            verdict = "none"
        lines = [
            f"coupling between {a.label} and {b.label}: {verdict} (score {score:g})",
            *(f"  tight because {reason}" for reason in tight),
            *_direction(self, a, b, forward),
            *_direction(self, b, a, backward),
            *(
                [
                    "  both touch: "
                    + ", ".join(
                        f"{self.nodes[f].qual}{' (written)' if written else ''}"
                        for f, (_, written) in sorted(shared.items())
                    )
                ]
                if shared
                else []
            ),
            f"formula: {FORMULAS['coupling']}",
        ]
        return {
            "a": _brief(a),
            "b": _brief(b),
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

    def report(self, include_tests: bool = False, top: int = 12) -> dict[str, Any]:
        modules = [
            n
            for n in self.nodes.values()
            if n.kind == "module" and (include_tests or not self.is_test(n))
        ]
        rows = []
        for module in sorted(modules, key=lambda m: m.id):
            group = self._group_cohesion(module)
            unstable = self.instability(module, include_tests)
            classes = [
                self._class_cohesion(c)
                for c in module.children
                if c.kind == "class"
                and sum(1 for m in c.children if m.kind == "method") >= 2
            ]
            rows.append(
                {
                    "module": module.path,
                    "members": group["members"],
                    "groups": group["groups"],
                    "relational": group["relational"],
                    **unstable,
                    "split_classes": [
                        {"class": c["node"]["qual"], "groups": c["groups"]}
                        for c in classes
                        if isinstance(c["groups"], int) and c["groups"] > 1
                    ],
                }
            )
        pairs = self._module_pairs(modules, include_tests)
        lines = [
            "module                                       members groups internal  Ca  Ce  instability  classes that split",
        ]
        for row in rows:
            relational = (
                "-" if row["relational"] is None else f"{row['relational']:.2f}"
            )
            split = ", ".join(
                f"{c['class']}({c['groups']})" for c in row["split_classes"]
            )
            lines.append(
                f"{row['module']:<45}{row['members']:>7}{row['groups']:>7}{relational:>9}{row['ca']:>4}{row['ce']:>4}{row['instability']:>13.2f}  {split}"
            )
        lines.append("")
        lines.append(f"most coupled module pairs (top {top}):")
        for pair in pairs[:top]:
            arrow = "<->" if pair["cycle"] else "->"
            lines.append(
                f"  {pair['label']:<8} {pair['score']:>6g}  {pair['a']} {arrow} {pair['b']}  ({pair['kinds']})"
            )
        cycles = [p for p in pairs if p["cycle"]]
        lines.append("")
        lines.append(
            "module cycles: "
            + (", ".join(f"{p['a']} <-> {p['b']}" for p in cycles) or "none")
        )
        lines += [
            "",
            f"cohesion: {FORMULAS['module']}",
            f"class cohesion: {FORMULAS['class']}",
            FORMULAS["instability"],
            f"coupling: {FORMULAS['coupling']}",
        ]
        return {"modules": rows, "pairs": pairs[: top * 3], "text": "\n".join(lines)}

    def blueprint(self, name: str) -> dict[str, Any]:
        node = self.resolve(name)
        graph = self._graph(node)
        titles = {n["id"]: _node_title(n) for n in graph["nodes"]}
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
                + (f"  in: {ins}" if ins else "")
                + (f"  out: {outs}" if outs else "")
            )
        steps = [f"{e['from']}-{e['fp']}->{e['to']}" for e in graph.get("exec", [])]
        if steps:
            lines.append("  order: " + ", ".join(steps))
        return {"node": _brief(node), "graph": graph, "text": "\n".join(lines)}

    def subtree(self, node: Node) -> frozenset[str]:
        if node.id not in self._subtrees:
            ids: set[str] = set()
            stack = [node]
            while stack:
                current = stack.pop()
                ids.add(current.id)
                stack.extend(current.children)
            self._subtrees[node.id] = frozenset(ids)
        return self._subtrees[node.id]

    def chain(self, node_id: str) -> list[Node]:
        out: list[Node] = []
        current = self.nodes.get(node_id)
        while current is not None:
            out.insert(0, current)
            current = current.parent
        return out

    def is_test(self, node: Node) -> bool:
        return node.path is not None and bool(TEST_PATH.search(node.path))

    def instability(self, module: Node, include_tests: bool = False) -> dict[str, Any]:
        mine = self.subtree(module)
        efferent = {
            self._module_of(e.target)
            for i in mine
            for e in self.outgoing.get(i, [])
            if e.target not in mine
        }
        afferent = {
            self._module_of(e.source)
            for i in mine
            for e in self.incoming.get(i, [])
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

    def _add_module(self, summary: dict[str, Any]) -> None:
        path = str(summary["path"])
        parts = path.split("/")
        parent = self.root
        prefix = ""
        for part in parts[:-1]:
            prefix = f"{prefix}/{part}" if prefix else part
            parent = self._add(f"pkg:{prefix}", "package", part, parent)
        module = self._add(f"mod:{path}", "module", parts[-1], parent, path=path)
        for symbol in summary.get("symbols", []):
            qual = str(symbol["qual"])
            if symbol["kind"] == "function":
                self._add(
                    f"fn:{path}:{qual}",
                    "function",
                    symbol["name"],
                    module,
                    path=path,
                    qual=qual,
                    line=symbol.get("line"),
                    end=symbol.get("end"),
                )
                continue
            holder = self._add(
                f"cls:{path}:{qual}",
                "class",
                symbol["name"],
                module,
                path=path,
                qual=qual,
                line=symbol.get("line"),
                end=symbol.get("end"),
            )
            for member, _ in symbol.get("members") or []:
                self._add(
                    f"f:{path}:{qual}.{member}",
                    "member",
                    member,
                    holder,
                    path=path,
                    qual=f"{qual}.{member}",
                )
            for name, _ in symbol.get("fields") or []:
                self._add(
                    f"f:{path}:{qual}.{name}",
                    "field",
                    name,
                    holder,
                    path=path,
                    qual=f"{qual}.{name}",
                )
            for method in symbol.get("methods") or []:
                method_qual = f"{qual}.{method['name']}"
                self._add(
                    f"m:{path}:{method_qual}",
                    "method",
                    method["name"],
                    holder,
                    path=path,
                    qual=method_qual,
                    line=method.get("line"),
                    end=method.get("end"),
                )
        for constant in summary.get("constants") or []:
            self._add(
                f"c:{path}:{constant[0]}",
                "constant",
                constant[0],
                module,
                path=path,
                qual=constant[0],
            )
        self.imports[path] = {
            str(entry["path"])
            for entry in summary.get("imports", [])
            if entry.get("path") and entry["path"] != path
        }

    def _add_library(self, library: dict[str, Any]) -> None:
        holder = self._add(
            str(library["id"]), "library", str(library["title"]), self.root
        )
        for module in library.get("modules", []):
            inner = self._add(
                f"libmod:{module['module']}", "libmodule", module["module"], holder
            )
            for name in module.get("names", []):
                self._add(f"libn:{module['module']}.{name}", "name", name, inner)

    def _add(
        self, node_id: str, kind: str, name: str, parent: Node, **extra: Any
    ) -> Node:
        if node_id in self.nodes:
            return self.nodes[node_id]
        node = Node(node_id, kind, name, parent, **extra)
        parent.children.append(node)
        self.nodes[node_id] = node
        return node

    def _edges(self, data: dict[str, Any]) -> list[Edge]:
        ids: list[str] = data.get("ids", [])
        edges = []
        for row in data.get("rows", []):
            source, target = ids[row[0]], ids[row[1]]
            if source not in self.nodes or target not in self.nodes:
                continue
            labels = tuple(row[3].split(",")) if len(row) > 3 and row[3] else ()
            edges.append(
                Edge(
                    source, target, frozenset(k for k in row[2].split(",") if k), labels
                )
            )
        return edges

    def _candidates(self, wanted: str) -> list[Node]:
        stem = wanted.replace(".", "/")
        as_paths = {stem + extension for extension in EXTENSIONS}
        exact = [
            node
            for node in self.nodes.values()
            if node.kind in CODE_KINDS
            and (
                node.path == wanted
                and node.kind == "module"
                or (node.kind == "module" and node.path in as_paths)
                or (node.kind == "package" and node.id == f"pkg:{wanted}")
                or node.qual == wanted
                or (node.path is not None and f"{node.path}:{node.qual}" == wanted)
            )
        ]
        if exact:
            return exact
        return [
            node
            for node in self.nodes.values()
            if node.kind in CODE_KINDS
            and node.qual is not None
            and node.qual.endswith(f".{wanted}")
        ]

    def _module_of(self, node_id: str) -> str | None:
        for node in reversed(self.chain(node_id)):
            if node.kind == "module":
                return node.path
        return None

    def _lift(
        self, edges: Iterable[Edge], end: Callable[[Edge], str], level: str
    ) -> list[tuple[str, Counter[str]]]:
        lifted: dict[str, Counter[str]] = {}
        for edge in edges:
            unit = self._unit(end(edge), level)
            lifted.setdefault(unit, Counter()).update(edge.kinds)
        return sorted(
            lifted.items(), key=lambda item: (-sum(item[1].values()), item[0])
        )

    def _unit(self, node_id: str, level: str) -> str:
        chain = self.chain(node_id)
        if level == "module":
            for node in chain:
                if node.kind in ("module", "library"):
                    return node.id
        for node in chain:
            if node.kind in ("class", "function", "libmodule"):
                return node.id
        return node_id

    def _shared_fields(
        self, a_ids: frozenset[str], b_ids: frozenset[str]
    ) -> dict[str, tuple[bool, bool]]:
        def touches(ids: frozenset[str]) -> dict[str, bool]:
            found: dict[str, bool] = {}
            for i in ids:
                for edge in self.outgoing.get(i, []):
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

    def _class_cohesion(self, holder: Node) -> dict[str, Any]:
        methods = [
            m
            for m in holder.children
            if m.kind == "method" and m.name not in CONSTRUCTORS
        ]
        fields = {f.id for f in self._class_fields(holder)}
        touches = {
            m.id: {
                e.target
                for e in self.outgoing.get(m.id, [])
                if e.target in fields and e.kinds & {"reads", "writes"}
            }
            for m in methods
        }
        calls = {
            m.id: {e.target for e in self.outgoing.get(m.id, []) if e.target in touches}
            for m in methods
        }
        usage = Counter(f for touched in touches.values() for f in touched)
        hubs = {
            f
            for f, n in usage.items()
            if len(methods) >= 4 and n / len(methods) > HUB_SHARE
        }
        base = {
            "node": _brief(holder),
            "methods": len(methods),
            "fields": len(fields),
            "field_use": {self.nodes[f].name: n for f, n in usage.most_common()},
            "formula": FORMULAS["class"],
        }
        if len(methods) < 2:
            text = f"class {holder.label}: {len(methods)} method(s) besides the constructor, too few to measure cohesion."
            return {**base, "groups": None, "label": "n/a", "text": text}
        groups = _groups(touches, calls, set())
        without_hubs = _groups(touches, calls, hubs) if hubs else groups
        verdict = _cohesion_label(len(groups))
        lines = [
            f"class {holder.label}: {verdict} cohesion, {len(groups)} group(s) of methods (LCOM4 = {len(groups)})",
            f"  {len(methods)} methods besides the constructor, {len(fields)} fields",
        ]
        if len(groups) > 1:
            lines += [
                f"  group {n}: {', '.join(sorted(self.nodes[i].name for i in g))}"
                for n, g in enumerate(groups, 1)
            ]
        if hubs:
            names = ", ".join(sorted(self.nodes[f].name for f in hubs))
            verdict_without = (
                "so the score flatters the class"
                if len(without_hubs) > len(groups)
                else "so they are not what holds it together"
            )
            lines.append(
                f"  hub fields used by most methods: {names}. Without them: {len(without_hubs)} group(s), {verdict_without}."
            )
        if usage:
            lines.append(
                "  field use: "
                + ", ".join(
                    f"{self.nodes[f].name}×{n}" for f, n in usage.most_common(10)
                )
            )
        lines.append(f"formula: {FORMULAS['class']}")
        return {
            **base,
            "groups": len(groups),
            "groups_without_hubs": len(without_hubs),
            "hubs": sorted(self.nodes[f].name for f in hubs),
            "members": [sorted(self.nodes[i].name for i in g) for g in groups],
            "label": verdict,
            "text": "\n".join(lines),
        }

    def _class_fields(self, holder: Node) -> list[Node]:
        seen: set[str] = set()
        fields: list[Node] = []
        stack = [holder]
        while stack:
            current = stack.pop()
            if current.id in seen:
                continue
            seen.add(current.id)
            fields += [f for f in current.children if f.kind == "field"]
            stack += [
                self.nodes[e.target]
                for e in self.outgoing.get(current.id, [])
                if "inherits" in e.kinds and e.target.startswith("cls:")
            ]
        return fields

    def _group_cohesion(self, node: Node) -> dict[str, Any]:
        kinds = MEMBER_KINDS if node.kind == "module" else {"module", "package"}
        members = [m for m in node.children if m.kind in kinds]
        owner = {i: m.id for m in members for i in self.subtree(m)}
        inside = self.subtree(node)
        links: dict[str, set[str]] = {m.id: set() for m in members}
        constants = {c.id for c in node.children if c.kind == "constant"}
        touches: dict[str, set[str]] = {m.id: set() for m in members}
        internal = external = 0
        for i in inside:
            for edge in self.outgoing.get(i, []):
                if edge.target in inside:
                    internal += 1
                    a, b = owner.get(edge.source), owner.get(edge.target)
                    if a and b and a != b:
                        links[a].add(b)
                    if a and edge.target in constants:
                        touches[a].add(edge.target)
                    if b and edge.source in constants:
                        touches[b].add(edge.source)
                elif self._module_of(edge.target) is not None:
                    external += 1
        groups = _groups(touches, links, set())
        relational = internal / (internal + external) if internal + external else None
        loners = [self.nodes[g[0]].name for g in groups if len(g) == 1]
        verdict = _cohesion_label(len(groups)) if len(members) > 1 else "n/a"
        lines = [
            f"{node.kind} {node.label}: {len(members)} member(s) in {len(groups)} linked group(s)"
            + (
                f", relational cohesion {relational:.2f} ({internal} links inside, {external} to other project modules)"
                if relational is not None
                else ""
            ),
        ]
        if len(groups) > 1:
            lines += [
                f"  group {n}: {', '.join(sorted(self.nodes[i].name for i in g))}"
                for n, g in enumerate(groups, 1)
                if len(g) > 1
            ]
            if loners:
                lines.append(
                    f"  unlinked to anything else here: {', '.join(sorted(loners))}"
                )
        if node.kind == "module":
            lines.append("  " + _instability_text(self.instability(node)))
        lines.append(f"formula: {FORMULAS[node.kind]}")
        return {
            "node": _brief(node),
            "members": len(members),
            "groups": len(groups),
            "group_members": [sorted(self.nodes[i].name for i in g) for g in groups],
            "internal": internal,
            "external": external,
            "relational": relational,
            "label": verdict,
            "formula": FORMULAS[node.kind],
            "text": "\n".join(lines),
        }

    def _function_cohesion(self, node: Node) -> dict[str, Any]:
        graph = self._graph(node)
        items = {n["id"]: n for n in graph["nodes"]}
        entry = next((i for i, n in items.items() if n["kind"] == "entry"), None)
        unpack = {
            e["to"]
            for e in graph["edges"]
            if e["from"] == entry
            and e["fp"] in ("self", "cls", "this")
            and items[e["to"]]["kind"] == "break"
        }
        skipped = unpack | ({entry} if entry else set())
        wired: dict[str, set[str]] = {i: set() for i in items if i not in skipped}
        for edge in graph["edges"]:
            if edge["from"] in wired and edge["to"] in wired:
                wired[edge["from"]].add(edge["to"])
                wired[edge["to"]].add(edge["from"])
        joined = {i: links for i, links in wired.items() if links}
        strands = _groups({i: set() for i in joined}, joined, set())
        lone = [
            i
            for i, links in wired.items()
            if not links and items[i]["kind"] != "return"
        ]
        verdict = _cohesion_label(len(strands)) if strands else "n/a"
        lines = [
            f"{node.kind} {node.label}: {len(strands)} independent dataflow strand(s), {verdict} cohesion",
            *(
                f"  strand {n}: {', '.join(_node_title(items[i]) for i in sorted(g, key=_order))}"
                for n, g in enumerate(strands, 1)
                if len(strands) > 1
            ),
        ]
        if lone:
            lines.append(
                f"  steps with no data wires: {', '.join(_node_title(items[i]) for i in sorted(lone, key=_order))}"
            )
        lines.append(f"formula: {FORMULAS['function']}")
        return {
            "node": _brief(node),
            "groups": len(strands),
            "strands": [
                [_node_title(items[i]) for i in sorted(g, key=_order)] for g in strands
            ],
            "unwired": [_node_title(items[i]) for i in lone],
            "label": verdict,
            "formula": FORMULAS["function"],
            "text": "\n".join(lines),
        }

    def _graph(self, node: Node) -> dict[str, Any]:
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

    def _module_pairs(
        self, modules: list[Node], include_tests: bool
    ) -> list[dict[str, Any]]:
        wanted = {m.path for m in modules}
        weights: dict[tuple[str, str], list[Edge]] = {}
        for edge in self.edges:
            a, b = self._module_of(edge.source), self._module_of(edge.target)
            if a is None or b is None or a == b or a not in wanted or b not in wanted:
                continue
            weights.setdefault((a, b), []).append(edge)
        pairs = []
        for a, b in {tuple(sorted(key)) for key in weights}:
            forward, backward = weights.get((a, b), []), weights.get((b, a), [])
            score = sum(e.weight for e in forward + backward)
            kinds = Counter(k for e in forward + backward for k in e.kinds)
            tight = (
                any(
                    e.kinds & {"inherits", "realizes", "writes"}
                    for e in forward + backward
                )
                or bool(forward and backward)
                or score >= TIGHT_SCORE
            )
            touched = len({e.target for e in forward + backward})
            label = (
                "tight"
                if tight
                else (
                    "moderate"
                    if score >= MODERATE_SCORE or touched > NARROW_SURFACE
                    else "loose"
                )
            )
            pairs.append(
                {
                    "a": a if forward or not backward else b,
                    "b": b if forward or not backward else a,
                    "score": score,
                    "label": label,
                    "cycle": bool(forward and backward),
                    "kinds": ", ".join(f"{k} {n}" for k, n in kinds.most_common()),
                }
            )
        return sorted(pairs, key=lambda p: (-float(p["score"]), str(p["a"])))


def _groups(
    touches: dict[str, set[str]], links: dict[str, set[str]], ignored: set[str]
) -> list[list[str]]:
    parent = {key: key for key in touches}

    def top(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def join(a: str, b: str) -> None:
        parent[top(a)] = top(b)

    by_field: dict[str, str] = {}
    for key, fields in touches.items():
        for f in fields - ignored:
            if f in by_field:
                join(key, by_field[f])
            else:
                by_field[f] = key
    for key, others in links.items():
        for other in others:
            if other in parent and key in parent:
                join(key, other)
    grouped: dict[str, list[str]] = {}
    for key in touches:
        grouped.setdefault(top(key), []).append(key)
    return sorted(grouped.values(), key=lambda g: (-len(g), sorted(g)))


def _cohesion_label(groups: int) -> str:
    return "high" if groups <= 1 else "medium" if groups == 2 else "low"


def _brief(node: Node) -> dict[str, Any]:
    return {
        "id": node.id,
        "kind": node.kind,
        "name": node.name,
        "path": node.path,
        "qual": node.qual,
        "line": node.line,
        "end": node.end,
    }


def _count(node: Node) -> str:
    kinds = Counter(child.kind for child in node.children)
    return ", ".join(
        f"{n} {kind}{'es' if kind == 'class' and n != 1 else '' if n == 1 else 's'}"
        for kind, n in kinds.most_common()
    )


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
    return {**_brief(node), "kinds": dict(kinds)}


def _direction(structure: Structure, a: Node, b: Node, edges: list[Edge]) -> list[str]:
    if not edges:
        return [f"  {a.label} -> {b.label}: nothing"]
    kinds = Counter(k for e in edges for k in e.kinds)
    targets = sorted(
        {
            structure.nodes[e.target].qual or structure.nodes[e.target].name
            for e in edges
        }
    )
    sources = sorted(
        {
            structure.nodes[e.source].qual or structure.nodes[e.source].name
            for e in edges
        }
    )
    return [
        f"  {a.label} -> {b.label}: {len(edges)} edge(s), {', '.join(f'{k} {n}' for k, n in kinds.most_common())}",
        f"    touches {len(targets)} of its members: {', '.join(targets[:12])}{' …' if len(targets) > 12 else ''}",
        f"    from {len(sources)} member(s): {', '.join(sources[:12])}{' …' if len(sources) > 12 else ''}",
    ]


def _direction_json(edges: list[Edge]) -> dict[str, Any]:
    return {
        "edges": len(edges),
        "kinds": dict(Counter(k for e in edges for k in e.kinds)),
        "touched": sorted({e.target for e in edges}),
        "from": sorted({e.source for e in edges}),
    }


def _instability_text(numbers: dict[str, Any]) -> str:
    return f"used by {numbers['ca']} project module(s), uses {numbers['ce']}: instability {numbers['instability']:.2f}"


def _node_title(item: dict[str, Any]) -> str:
    title = str(item.get("title", item["kind"]))
    if item.get("expr"):
        title += " [" + " ".join(str(line).strip() for line in item["expr"]) + "]"
    if item.get("code"):
        title += f" [{item['code']}]"
    return title


def _order(node_id: str) -> int:
    digits = "".join(ch for ch in node_id if ch.isdigit())
    return int(digits) if digits else 0
