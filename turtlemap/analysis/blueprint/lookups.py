import json
from collections.abc import Sequence

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.captures import reassigned_globals
from turtlemap.analysis.blueprint.code_shapes import (
    assigned_names,
    is_literal_expression,
)
from turtlemap.analysis.blueprint.members import Member, members_of
from turtlemap.analysis.blueprint.text import LITERAL_LIMIT, shorten
from turtlemap.analysis.blueprint.values import STR, Value
from turtlemap.analysis.types import (
    UNKNOWN,
    PinType,
    TypeResolver,
    TypeSystem,
    literal_type,
)
from turtlemap.analysis.workspace.parsed import ParsedModule, SymbolRef


class TypeLookups:
    def __init__(self, system: TypeSystem, module: ParsedModule) -> None:
        self.system = system
        self.workspace = system.workspace
        self.module = module
        self.profile = module.language.profile
        self.module_variables = _module_variables(module)
        self.reassigned_globals = reassigned_globals(module.body) & frozenset(
            self.module_variables
        )
        self._resolvers: dict[str, TypeResolver] = {}
        self._members: dict[SymbolRef, dict[str, Member]] = {}

    def annotation(self, annotation: m.TypeExpr | None) -> PinType:
        return (
            self.resolver(self.module).annotation(annotation)
            if annotation is not None
            else UNKNOWN
        )

    def exception(self, annotation: m.Expr | None) -> PinType:
        dotted = m.dotted_name(annotation) if annotation is not None else None
        if annotation is not None and dotted is not None:
            return self.annotation(
                m.TypeName(
                    annotation.line,
                    annotation.end_line,
                    dotted,
                    origin=annotation.origin,
                )
            )
        return PinType(self.profile.default_exception, "object")

    def module_variable(self, name: str) -> PinType:
        annotation, value = self.module_variables[name]
        return (
            self.annotation(annotation)
            if annotation is not None
            else self.literal_type_of(value)
        )

    def literal_type_of(self, value: m.Expr | None) -> PinType:
        literal = self.literal(value) if value is not None else None
        return literal.type if literal is not None else UNKNOWN

    def literal(self, expression: m.Expr) -> Value | None:
        if not is_literal_expression(expression):
            return None
        if isinstance(expression, m.Literal):
            if isinstance(expression.value, str):
                return Value(
                    STR,
                    literal=shorten(
                        json.dumps(expression.value, ensure_ascii=False),
                        LITERAL_LIMIT,
                    ),
                )
            if expression.value is Ellipsis:
                return Value(UNKNOWN, literal="...")
            literal = shorten(self.module.language.text(expression), LITERAL_LIMIT)
            if expression.value is None:
                return Value(self.none(), literal=literal)
            return Value(literal_type(expression.value), literal=literal)
        text = self.module.language.text(expression)
        if len(text) > LITERAL_LIMIT:
            return None
        if isinstance(expression, m.Unary) and isinstance(
            expression.operand, m.Literal
        ):
            return Value(literal_type(expression.operand.value), literal=text)
        if isinstance(expression, m.Sequence):
            entry = self.profile.sequence_kinds.get(expression.kind)
            return Value(self.profile_type(entry), literal=text)
        if isinstance(expression, m.Mapping):
            return Value(PinType(*self.profile.mapping_kind), literal=text)
        return Value(UNKNOWN, literal=text)

    def none(self) -> PinType:
        return PinType(self.profile.none_text, "none")

    def none_literal(self) -> Value:
        return Value(self.none(), literal=self.profile.none_text)

    def profile_type(self, entry: tuple[str, str] | None) -> PinType:
        return PinType(*entry) if entry is not None else UNKNOWN

    def attribute_chain(
        self, base: Value, attributes: Sequence[str]
    ) -> tuple[PinType, tuple[m.TypeExpr, ParsedModule] | None]:
        current = base.type
        annotation: tuple[m.TypeExpr, ParsedModule] | None = None
        for attribute in attributes:
            member = self.member(current, attribute)
            if member is None:
                return UNKNOWN, None
            current, annotation = self.member_type(member), (
                (member.annotation, member.module)
                if member.annotation is not None
                else None
            )
        return current, annotation

    def member(self, owner: PinType, attribute: str) -> Member | None:
        if owner.ref is None or self.workspace.parsed_class(owner.ref) is None:
            return None
        return self.class_members(owner.ref).get(attribute)

    def member_type(self, member: Member) -> PinType:
        if member.is_method:
            return PinType("method", "callable")
        return (
            self.resolver(member.module).annotation(member.annotation)
            if member.annotation is not None
            else UNKNOWN
        )

    def class_members(self, ref: SymbolRef) -> dict[str, Member]:
        cached = self._members.get(ref)
        if cached is not None:
            return cached
        members: dict[str, Member] = {}
        for ancestor in self.workspace.class_ancestry(ref):
            parsed = self.workspace.parsed_class(ancestor)
            module = self.workspace.module(ancestor.path)
            if parsed is None or module is None:
                continue
            for name, member in members_of(parsed.node, module, self.workspace).items():
                members.setdefault(name, member)
        self._members[ref] = members
        return members

    def class_fields(self, ref: SymbolRef) -> dict[str, PinType]:
        fields: dict[str, PinType] = {}
        for ancestor in reversed(self.workspace.class_ancestry(ref)):
            parsed = self.workspace.parsed_class(ancestor)
            module = self.workspace.module(ancestor.path)
            if parsed is None or module is None:
                continue
            for statement in parsed.node.body:
                if (
                    isinstance(statement, m.Assign)
                    and statement.annotation is not None
                    and isinstance(statement.targets[0], m.Name)
                    and not _is_class_variable(module, statement.annotation)
                ):
                    fields[statement.targets[0].id] = self.resolver(module).annotation(
                        statement.annotation
                    )
        return fields

    def element(self, value: Value) -> PinType:
        if value.annotation is None:
            return UNKNOWN
        annotation, module = value.annotation
        if isinstance(annotation, m.TypeName) and annotation.args:
            names = module.language.profile.types
            base = annotation.dotted.rsplit(".", 1)[-1]
            if (
                base in names.sequences
                or base in names.mappings
                or base in names.tuples
            ):
                return self.resolver(module).annotation(annotation.args[0])
        return UNKNOWN

    def item(self, container: Value, key: m.Expr) -> PinType:
        if container.annotation is None:
            return UNKNOWN
        annotation, module = container.annotation
        if not isinstance(annotation, m.TypeName) or not annotation.args:
            return UNKNOWN
        names = module.language.profile.types
        base = annotation.dotted.rsplit(".", 1)[-1]
        arguments = annotation.args
        if base in names.mappings and len(arguments) == 2:
            return self.resolver(module).annotation(arguments[1])
        if base in names.sequences and not isinstance(key, m.Slice):
            return self.resolver(module).annotation(arguments[0])
        if (
            base in names.tuples
            and isinstance(key, m.Literal)
            and isinstance(key.value, int)
            and -len(arguments) <= key.value < len(arguments)
        ):
            chosen = (
                arguments[0]
                if len(arguments) == 2 and isinstance(arguments[1], m.TypeLiteral)
                else arguments[key.value]
            )
            return self.resolver(module).annotation(chosen)
        return UNKNOWN

    def resolver(self, module: ParsedModule) -> TypeResolver:
        resolver = self._resolvers.get(module.path)
        if resolver is None or resolver.module is not module:
            resolver = self.system.resolver(module)
            self._resolvers[module.path] = resolver
        return resolver


def _module_variables(
    module: ParsedModule,
) -> dict[str, tuple[m.TypeExpr | None, m.Expr | None]]:
    variables: dict[str, tuple[m.TypeExpr | None, m.Expr | None]] = {}
    pending: list[m.Stmt] = list(module.body)
    while pending:
        statement = pending.pop(0)
        if isinstance(statement, m.Assign):
            if (
                statement.annotation is not None
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], m.Name)
            ):
                variables[statement.targets[0].id] = (
                    statement.annotation,
                    statement.value,
                )
                continue
            for target in statement.targets:
                for name in assigned_names(target) or []:
                    variables.setdefault(name.lstrip("*"), (None, statement.value))
        elif isinstance(statement, m.If):
            pending.extend([*statement.body, *statement.orelse])
        elif isinstance(statement, m.Try):
            pending.extend(
                [
                    *statement.body,
                    *statement.orelse,
                    *statement.finalbody,
                    *(item for handler in statement.handlers for item in handler.body),
                ]
            )
    for name in module.top_level:
        variables.pop(name, None)
    return variables


def _is_class_variable(module: ParsedModule, annotation: m.TypeExpr) -> bool:
    return (
        isinstance(annotation, m.TypeName)
        and annotation.dotted.rsplit(".", 1)[-1]
        in module.language.profile.types.class_variable
    )
