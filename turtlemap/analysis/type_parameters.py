from collections.abc import Iterable
from dataclasses import dataclass

from turtlemap.analysis import model as m
from turtlemap.analysis.workspace.parsed import ParsedModule
from turtlemap.analysis.workspace.workspace import Workspace
from turtlemap.languages.language import TypeParameter


@dataclass(frozen=True)
class FoundParameter:
    module: ParsedModule
    parameter: TypeParameter
    line: int

    @property
    def id(self) -> str:
        return type_parameter_id(self.module.path, self.parameter.name)


def type_parameter_id(path: str, name: str) -> str:
    return f"tv:{path}:{name}"


class TypeParameters:
    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace
        self._declared: dict[str, dict[str, FoundParameter]] = {}

    def declared(self, module: ParsedModule) -> dict[str, FoundParameter]:
        found = self._declared.get(module.path)
        if found is None:
            found = {}
            for statement in module.body:
                if not isinstance(statement, m.Assign):
                    continue
                parameter = module.language.type_parameter(statement)
                if parameter is not None:
                    found[parameter.name] = FoundParameter(
                        module, parameter, statement.line
                    )
            self._declared[module.path] = found
        return found

    def find(self, module: ParsedModule, dotted: str) -> FoundParameter | None:
        head, _, rest = dotted.partition(".")
        if not rest and head in self.declared(module):
            return self.declared(module)[head]
        binding = module.imports.get(head)
        if binding is None:
            if rest:
                return None
            for neighbour in self._workspace.script_neighbours(module):
                if head in self.declared(neighbour):
                    return self.declared(neighbour)[head]
            return None
        module_name, _, name = (
            binding.absolute + ("." + rest if rest else "")
        ).rpartition(".")
        path = self._workspace.index.find_module(module_name, near=module.path)
        target = self._workspace.module(path) if path else None
        if target is None:
            return None
        return self.declared(target).get(name)

    def mentioned(
        self, module: ParsedModule, nodes: Iterable[m.Node]
    ) -> list[FoundParameter]:
        found: dict[str, FoundParameter] = {}
        for root in nodes:
            for node in m.walk(root):
                dotted = (
                    node.dotted
                    if isinstance(node, m.TypeName)
                    else m.dotted_name(node) if isinstance(node, m.Expr) else None
                )
                parameter = self.find(module, dotted) if dotted else None
                if parameter is not None:
                    found.setdefault(parameter.id, parameter)
        return list(found.values())


def bound_names(parameter: TypeParameter) -> list[str]:
    names: list[str] = []
    for bound in (
        [parameter.bound, *parameter.constraints]
        if parameter.bound is not None
        else list(parameter.constraints)
    ):
        dotted = m.dotted_name(bound)
        if dotted is None and isinstance(bound, m.Literal):
            dotted = str(bound.value) if isinstance(bound.value, str) else None
        if dotted is not None:
            names.append(dotted)
    return names
