from collections.abc import Iterator
from dataclasses import dataclass

from code_blueprints.analysis import model as m
from code_blueprints.analysis.unpacking import receiver_fields
from code_blueprints.analysis.workspace.parsed import ParsedModule
from code_blueprints.analysis.workspace.workspace import Workspace


@dataclass(frozen=True)
class Member:
    annotation: m.TypeExpr | None
    module: ParsedModule
    is_method: bool = False


def members_of(
    cls: m.ClassDecl, module: ParsedModule, workspace: Workspace
) -> dict[str, Member]:
    members: dict[str, Member] = {}
    for statement in cls.body:
        if (
            isinstance(statement, m.Assign)
            and statement.annotation is not None
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], m.Name)
        ):
            members.setdefault(
                statement.targets[0].id, Member(statement.annotation, module)
            )
        elif isinstance(statement, m.FunctionDef):
            function = statement.function
            if function.is_property:
                members.setdefault(function.name, Member(function.returns, module))
            else:
                members.setdefault(function.name, Member(None, module, is_method=True))
    initializer = next(
        (
            statement.function
            for statement in cls.body
            if isinstance(statement, m.FunctionDef)
            and statement.function.is_constructor
            and not statement.function.is_async
        ),
        None,
    )
    if initializer is not None:
        for name, annotation in _initializer_assignments(initializer, module):
            members.setdefault(name, Member(annotation, module))
        for name, member in _unpacked_assignments(initializer, module, workspace):
            members.setdefault(name, member)
    return members


def _initializer_assignments(
    initializer: m.FunctionDecl, module: ParsedModule
) -> Iterator[tuple[str, m.TypeExpr | None]]:
    receiver = (
        initializer.implicit_receiver or module.language.profile.instance_receiver
    )
    parameters = {
        parameter.name: parameter.annotation for parameter in initializer.params
    }
    for node in m.walk(initializer):
        if not isinstance(node, m.Assign):
            continue
        for target in node.targets:
            if not (
                isinstance(target, m.Member)
                and isinstance(target.value, m.Name)
                and target.value.id == receiver
            ):
                continue
            if node.annotation is not None:
                yield target.attr, node.annotation
            else:
                yield target.attr, (
                    parameters.get(node.value.id)
                    if isinstance(node.value, m.Name)
                    else None
                )


def _unpacked_assignments(
    initializer: m.FunctionDecl, module: ParsedModule, workspace: Workspace
) -> Iterator[tuple[str, Member]]:
    receiver = (
        initializer.implicit_receiver or module.language.profile.instance_receiver
    )
    parameters = {
        parameter.name: parameter.annotation for parameter in initializer.params
    }
    for node in m.walk(initializer):
        if not isinstance(node, m.Assign):
            continue
        for field in receiver_fields(node, receiver, module, workspace):
            if field.annotation is not None:
                yield field.name, Member(field.annotation[0], field.annotation[1])
            elif isinstance(field.value, m.Name):
                yield field.name, Member(parameters.get(field.value.id), module)
            else:
                yield field.name, Member(None, module)
