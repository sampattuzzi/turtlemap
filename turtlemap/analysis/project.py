import threading
import time
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from turtlemap.analysis.dependencies import DependencyCollector, edge_table
from turtlemap.analysis.blueprint.builder import build_function_graph
from turtlemap.analysis.outline import function_code, module_outline
from turtlemap.analysis.symbols import module_summary
from turtlemap.analysis.types import TypeSystem
from turtlemap.analysis.workspace.parsed import (
    ParseFailure,
    ParsedModule,
    library_of,
)
from turtlemap.analysis.workspace.reads import Keys
from turtlemap.analysis.workspace.workspace import Workspace

ExternalName = tuple[str, str | None]


@dataclass(frozen=True)
class Piece:
    path: str
    module: dict[str, Any] | None
    failure: str | None
    edges: list[list[Any]]
    external: frozenset[ExternalName]
    keys: Keys

    def to_json(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "failure": self.failure,
            "edges": self.edges,
            "external": sorted([module, name or ""] for module, name in self.external),
        }

    @classmethod
    def from_json(cls, path: str, data: dict[str, Any], keys: Keys) -> "Piece":
        return cls(
            path,
            data["module"],
            data["failure"],
            data["edges"],
            frozenset((module, name or None) for module, name in data["external"]),
            keys,
        )


class Project:
    def __init__(
        self,
        root: Path,
        files: list[str] | None = None,
        name: str | None = None,
        display_root: Path | None = None,
    ) -> None:
        self.root = root.resolve()
        self.name = name or self.root.name
        self.display_root = display_root or self.root
        self.workspace = (
            Workspace.discover(self.root)
            if files is None
            else Workspace(self.root, files)
        )
        self.types = TypeSystem(self.workspace)
        self._lock = threading.RLock()
        self._overview: dict[str, Any] | None = None
        self._pieces: tuple[Sequence[Piece], float] | None = None
        self._known: dict[str, Piece] = {}

    def overview(self) -> dict[str, Any]:
        with self._lock:
            if self._overview is None:
                started = time.perf_counter()
                pieces, seconds = self._pieces or (
                    self.pieces(self.workspace.index.files),
                    time.perf_counter() - started,
                )
                self._overview = self.assemble(pieces, seconds)
            return self._overview

    def use_pieces(self, pieces: Sequence[Piece], seconds: float) -> None:
        with self._lock:
            self._pieces = (pieces, seconds)
            self._overview = None
            self._known = {piece.path: piece for piece in pieces}

    def remember(self, pieces: Iterable[Piece]) -> None:
        with self._lock:
            self._known.update((piece.path, piece) for piece in pieces)

    def pieces(self, paths: Iterable[str]) -> list[Piece]:
        collector = DependencyCollector(self.types)
        with self._lock:
            return [self._piece(path, collector) for path in paths]

    def edges_of(self, path: str) -> list[list[Any]]:
        if not self.workspace.index.contains(path):
            return []
        with self._lock:
            piece = self._known.get(path)
            if piece is None:
                piece = self.pieces([path])[0]
                self._known[path] = piece
        return piece.edges

    def assemble(self, pieces: Sequence[Piece], seconds: float) -> dict[str, Any]:
        modules = [piece.module for piece in pieces if piece.module is not None]
        used = {name for piece in pieces for name in piece.external}
        return {
            "name": self.name,
            "root": str(self.display_root),
            "modules": modules,
            "failures": [
                {"path": piece.path, "message": piece.failure}
                for piece in pieces
                if piece.failure is not None
            ],
            "libraries": _libraries(modules, used),
            "edges": _edges_by_file(pieces),
            "seconds": round(seconds, 2),
        }

    def changes(
        self,
        rebuilt: Sequence[Piece],
        removed: Collection[str],
        everything: Collection[Piece],
    ) -> dict[str, Any]:
        modules = [piece.module for piece in everything if piece.module is not None]
        used = {name for piece in everything for name in piece.external}
        return {
            **self.assemble(rebuilt, 0),
            "rebuilt": [piece.path for piece in rebuilt],
            "removed": sorted(removed),
            "libraries": _libraries(modules, used),
        }

    def reload(self) -> None:
        with self._lock:
            self.workspace.refresh()
            self.types = TypeSystem(self.workspace)
            self._overview = None
            self._pieces = None

    def outline(self, path: str) -> list[dict[str, Any]] | None:
        module = self._module(path)
        return module_outline(module) if module is not None else None

    def function(self, path: str, qual: str) -> dict[str, Any] | None:
        module = self._module(path)
        if module is None or qual not in module.functions:
            return None
        function = module.functions[qual]
        with self._lock:
            graph = build_function_graph(self.types, module, function)
        return {
            "path": path,
            "qual": qual,
            "line": function.node.line,
            "code": function_code(module, function),
            "graph": graph,
        }

    def module_summary(self, path: str) -> dict[str, Any] | None:
        known = self._known.get(path)
        if known is not None:
            return known.module
        module = self._module(path)
        return module_summary(self.types, module) if module is not None else None

    def parse_failure(self, path: str) -> str | None:
        if not self.workspace.index.contains(path):
            return None
        parsed = self.workspace.parsed(path)
        return parsed.message if isinstance(parsed, ParseFailure) else None

    def _module(self, path: str) -> ParsedModule | None:
        if not self.workspace.index.contains(path):
            return None
        return self.workspace.module(path)

    def _piece(self, path: str, collector: DependencyCollector) -> Piece:
        with self.workspace.reads.recording() as keys:
            parsed = self.workspace.parsed(path)
            if isinstance(parsed, ParseFailure):
                return Piece(
                    path, None, parsed.message, [], frozenset(), frozenset(keys)
                )
            try:
                module = module_summary(self.types, parsed)
                edges, external = collector.collect_alone(parsed)
            except RecursionError as error:
                failure = f"RecursionError: {error}"
                return Piece(path, None, failure, [], frozenset(), frozenset(keys))
        return Piece(path, module, None, edges, external, frozenset(keys))


def _edges_by_file(pieces: Sequence[Piece]) -> dict[str, Any]:
    table = edge_table(edge for piece in pieces for edge in piece.edges)
    table["files"] = [[piece.path, len(piece.edges)] for piece in pieces if piece.edges]
    return table


def _libraries(
    modules: list[dict[str, Any]], used: set[tuple[str, str | None]]
) -> list[dict[str, Any]]:
    names: dict[str, set[str]] = {}
    for summary in modules:
        for entry in summary["imports"]:
            if entry["path"] is None:
                names.setdefault(entry["module"], set()).update(entry["names"])
    for module, name in used:
        bucket = names.setdefault(module, set())
        if name:
            bucket.add(name)
    libraries: dict[str, dict[str, Any]] = {}
    for module in sorted(names):
        lib = library_of(module)
        library = libraries.setdefault(
            lib,
            {
                "id": f"lib:{lib}",
                "title": "standard library" if lib == "stdlib" else lib,
                "modules": [],
            },
        )
        library["modules"].append({"module": module, "names": sorted(names[module])})
    return sorted(
        libraries.values(), key=lambda lib: (lib["id"] != "lib:stdlib", lib["title"])
    )
