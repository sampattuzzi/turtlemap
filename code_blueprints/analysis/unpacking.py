from dataclasses import dataclass

from code_blueprints.analysis import model as m
from code_blueprints.analysis.workspace.parsed import ParsedModule, SymbolRef
from code_blueprints.analysis.workspace.workspace import Workspace


@dataclass(frozen=True)
class UnpackedField:
    name: str
    value: m.Expr | None
    annotation: tuple[m.TypeExpr, ParsedModule] | None


def receiver_fields(
    statement: m.Assign, receiver: str, module: ParsedModule, workspace: Workspace
) -> list[UnpackedField]:
    fields: list[UnpackedField] = []
    for target in statement.targets:
        if not isinstance(target, m.Sequence):
            continue
        values = _parts_of(statement.value, len(target.elements))
        annotations = _returned_parts(
            statement.value, len(target.elements), module, workspace
        )
        for index, element in enumerate(target.elements):
            if (
                isinstance(element, m.Member)
                and isinstance(element.value, m.Name)
                and element.value.id == receiver
            ):
                fields.append(
                    UnpackedField(
                        element.attr,
                        values[index] if values is not None else None,
                        annotations[index] if annotations is not None else None,
                    )
                )
    return fields


def _parts_of(value: m.Expr | None, count: int) -> list[m.Expr] | None:
    if (
        isinstance(value, m.Sequence)
        and len(value.elements) == count
        and not any(isinstance(element, m.Spread) for element in value.elements)
    ):
        return list(value.elements)
    return None


def _returned_parts(
    value: m.Expr | None, count: int, module: ParsedModule, workspace: Workspace
) -> list[tuple[m.TypeExpr, ParsedModule]] | None:
    if isinstance(value, m.Await):
        value = value.value
    if not isinstance(value, m.Call):
        return None
    dotted = m.dotted_name(value.func)
    resolved = workspace.resolve(module, dotted) if dotted is not None else None
    if not isinstance(resolved, SymbolRef):
        return None
    function = workspace.parsed_function(resolved)
    owner = workspace.module(resolved.path)
    if function is None or owner is None:
        return None
    returns = function.node.returns
    if (
        not isinstance(returns, m.TypeName)
        or returns.dotted.rsplit(".", 1)[-1] not in owner.language.profile.types.tuples
        or len(returns.args) != count
    ):
        return None
    return [(part, owner) for part in returns.args]
