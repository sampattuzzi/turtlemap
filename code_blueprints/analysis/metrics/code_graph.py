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

TEST_PATH = re.compile(
    r"(^|/)(tests?|testing|__tests__)/|(^|/)test_[^/]*\.py$|_test\.py$"
    r"|\.(test|spec)\.[cm]?[jt]sx?$"
)

CODE_KINDS = frozenset(
    {"package", "module", "class", "function", "method", "field", "constant"}
)


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
    lines: int | None = None
    complexity: int | None = None
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


class CodeGraph:
    def __init__(self, overview: dict[str, Any]) -> None:
        self.root = Node("root", "root", str(overview.get("name", "project")), None)
        self.nodes: dict[str, Node] = {"root": self.root}
        self.imports: dict[str, set[str]] = {}
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
            "matches": [brief(node) for node in found[:limit]],
            "text": "\n".join(lines) or f"Nothing matches {text!r}.",
        }

    def tree(self, name: str | None = None, depth: int = 2) -> dict[str, Any]:
        start = self.resolve(name) if name else self.root
        lines: list[str] = []

        def walk(node: Node, level: int) -> None:
            for child in node.children:
                if child.kind in ("library", "libmodule", "name") and node is self.root:
                    continue
                count = f" ({child_counts(child)})" if child.children else ""
                lines.append(
                    f"{'  ' * level}{child.kind} {child.name}{count}  [{child.id}]"
                )
                if level + 1 < depth:
                    walk(child, level + 1)

        walk(start, 0)
        return {"node": brief(start), "text": "\n".join(lines) or "(empty)"}

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

    def _add_module(self, summary: dict[str, Any]) -> None:
        path = str(summary["path"])
        parts = path.split("/")
        parent = self._add_packages(parts[:-1])
        module = self._add(
            f"mod:{path}",
            "module",
            parts[-1],
            parent,
            path=path,
            lines=summary.get("lines"),
        )
        for symbol in summary.get("symbols", []):
            if symbol["kind"] == "function":
                self._add_function(symbol, path, module)
            else:
                self._add_class(symbol, path, module)
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

    def _add_packages(self, folders: list[str]) -> Node:
        parent = self.root
        prefix = ""
        for part in folders:
            prefix = f"{prefix}/{part}" if prefix else part
            parent = self._add(f"pkg:{prefix}", "package", part, parent)
        return parent

    def _add_function(self, symbol: dict[str, Any], path: str, module: Node) -> None:
        qual = str(symbol["qual"])
        self._add(
            f"fn:{path}:{qual}",
            "function",
            symbol["name"],
            module,
            path=path,
            qual=qual,
            line=symbol.get("line"),
            end=symbol.get("end"),
            complexity=symbol.get("complexity"),
        )

    def _add_class(self, symbol: dict[str, Any], path: str, module: Node) -> None:
        qual = str(symbol["qual"])
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
            self._add_field(holder, "member", member)
        for name, _ in symbol.get("fields") or []:
            self._add_field(holder, "field", name)
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
                complexity=method.get("complexity"),
            )

    def _add_field(self, holder: Node, kind: str, name: str) -> None:
        qual = f"{holder.qual}.{name}"
        self._add(
            f"f:{holder.path}:{qual}", kind, name, holder, path=holder.path, qual=qual
        )

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
        code = [node for node in self.nodes.values() if node.kind in CODE_KINDS]
        exact = [node for node in code if _names_exactly(node, wanted, as_paths)]
        if exact:
            return exact
        return [
            node
            for node in code
            if node.qual is not None and node.qual.endswith(f".{wanted}")
        ]

    def module_of(self, node_id: str) -> str | None:
        for node in reversed(self.chain(node_id)):
            if node.kind == "module":
                return node.path
        return None

    def lift(
        self, edges: Iterable[Edge], end: Callable[[Edge], str], level: str
    ) -> list[tuple[str, Counter[str]]]:
        lifted: dict[str, Counter[str]] = {}
        for edge in edges:
            unit = self._unit(end(edge), level)
            lifted.setdefault(unit, Counter()).update(sorted(edge.kinds))
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


def brief(node: Node) -> dict[str, Any]:
    return {
        "id": node.id,
        "kind": node.kind,
        "name": node.name,
        "path": node.path,
        "qual": node.qual,
        "line": node.line,
        "end": node.end,
    }


def child_counts(node: Node) -> str:
    kinds = Counter(child.kind for child in node.children)
    return ", ".join(
        f"{n} {kind}{'es' if kind == 'class' and n != 1 else '' if n == 1 else 's'}"
        for kind, n in kinds.most_common()
    )


def _names_exactly(node: Node, wanted: str, as_paths: set[str]) -> bool:
    if node.kind == "module" and (node.path == wanted or node.path in as_paths):
        return True
    if node.kind == "package" and node.id == f"pkg:{wanted}":
        return True
    if node.qual == wanted:
        return True
    return node.path is not None and f"{node.path}:{node.qual}" == wanted
