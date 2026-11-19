import threading
import time
from pathlib import Path
from typing import Any

from turtlemap.analysis.dependencies import DependencyCollector
from turtlemap.analysis.blueprint.builder import build_function_graph
from turtlemap.analysis.outline import function_code, module_outline
from turtlemap.analysis.symbols import module_summary
from turtlemap.analysis.types import TypeSystem
from turtlemap.analysis.workspace.parsed import (
    ParseFailure,
    ParsedModule,
    library_of,
)
from turtlemap.analysis.workspace.workspace import Workspace


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

    def overview(self) -> dict[str, Any]:
        with self._lock:
            if self._overview is None:
                self._overview = self._build_overview()
            return self._overview

    def reload(self) -> None:
        with self._lock:
            self.workspace.refresh()
            self.types = TypeSystem(self.workspace)
            self._overview = None

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
        module = self._module(path)
        return module_summary(self.types, module) if module is not None else None

    def _module(self, path: str) -> ParsedModule | None:
        if not self.workspace.index.contains(path):
            return None
        return self.workspace.module(path)

    def _build_overview(self) -> dict[str, Any]:
        started = time.perf_counter()
        modules: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        collector = DependencyCollector(self.types)
        for path in self.workspace.index.files:
            parsed = self.workspace.parsed(path)
            if isinstance(parsed, ParseFailure):
                failures.append({"path": path, "message": parsed.message})
                continue
            try:
                modules.append(module_summary(self.types, parsed))
                collector.collect(parsed)
            except RecursionError as error:
                failures.append({"path": path, "message": f"RecursionError: {error}"})
        return {
            "name": self.name,
            "root": str(self.display_root),
            "modules": modules,
            "failures": failures,
            "libraries": _libraries(modules, collector.external_names),
            "edges": collector.result(),
            "seconds": round(time.perf_counter() - started, 2),
        }


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
