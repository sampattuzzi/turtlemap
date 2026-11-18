from typing import Any

from code_blueprints.analysis import model as m
from code_blueprints.analysis.types import TypeSystem
from code_blueprints.analysis.workspace.parsed import (
    ParsedModule,
    SymbolRef,
    library_of,
)


def module_imports(types: TypeSystem, module: ParsedModule) -> list[dict[str, Any]]:
    groups = _ImportGroups(types, module.path)
    for statement in module.import_statements:
        if statement.whole:
            groups.whole_modules(statement)
        elif statement.module is not None:
            groups.names_from(statement, statement.module)
    return groups.entries()


def module_of_path(types: TypeSystem, path: str) -> str:
    module = types.workspace.module(path)
    return module.name if module else path


class _ImportGroups:
    def __init__(self, types: TypeSystem, near: str) -> None:
        self.types = types
        self.workspace = types.workspace
        self.near = near
        self.grouped: dict[str, dict[str, Any]] = {}

    def whole_modules(self, statement: m.Import) -> None:
        for alias in statement.names:
            path = self.workspace.index.find_module(alias.name, near=self.near)
            if path is not None or not self.workspace.index.is_package(
                alias.name, near=self.near
            ):
                self._add(alias.name, path, None)

    def names_from(self, statement: m.Import, base: str) -> None:
        for alias in statement.names:
            if alias.name != "*":
                self._name_from(statement, base, alias.name)

    def entries(self) -> list[dict[str, Any]]:
        out = list(self.grouped.values())
        for entry in out:
            if entry["path"] is None:
                entry["lib"] = library_of(entry["module"])
        return out

    def _name_from(self, statement: m.Import, base: str, name: str) -> None:
        submodule = (
            self.workspace.index.find_module(f"{base}.{name}", near=self.near)
            if base
            else None
        )
        if submodule is not None:
            self._add(f"{base}.{name}", submodule, None)
            return
        path = self.workspace.index.find_module(base, near=self.near) if base else None
        if path is None and (
            statement.level > 0 or self.workspace.index.is_package(base, near=self.near)
        ):
            self._reexported(f"{base}.{name}")
            return
        self._add(base, path, name)

    def _reexported(self, dotted: str) -> None:
        resolved = self.workspace.resolve_absolute(dotted, near=self.near)
        if isinstance(resolved, SymbolRef):
            self._add(
                module_of_path(self.types, resolved.path),
                resolved.path,
                resolved.sym.split(".")[0],
            )

    def _add(self, name: str, path: str | None, imported: str | None) -> None:
        entry = self.grouped.setdefault(
            name, {"module": name, "path": path, "names": []}
        )
        if imported and imported not in entry["names"]:
            entry["names"].append(imported)
