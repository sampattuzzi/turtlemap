from tree_sitter import Node as Syntax

from code_blueprints.analysis import model as m
from code_blueprints.languages.javascript import literals
from code_blueprints.languages.javascript import naming
from code_blueprints.languages.javascript import nodes as ts
from code_blueprints.languages.javascript.lowering.ports import (
    ClassesPort,
    ExpressionsPort,
    FunctionsPort,
    StatementsPort,
)
from code_blueprints.languages.javascript.lowering.state import LoweringState


class Exports:
    classes: ClassesPort
    expressions: ExpressionsPort
    functions: FunctionsPort
    statements: StatementsPort

    def __init__(self, state: LoweringState) -> None:
        self.state = state

    def statement(self, node: Syntax) -> list[m.Stmt]:
        declaration = node.child_by_field_name("declaration")
        if declaration is not None:
            return self._declaration(node, declaration)
        source = node.child_by_field_name("source")
        clause = next(
            (c for c in node.named_children if c.type == "export_clause"), None
        )
        if source is not None:
            return self._reexport(node, source, clause)
        if clause is not None:
            self._alias_locals(clause)
            return []
        return self._default(node)

    def _declaration(self, node: Syntax, declaration: Syntax) -> list[m.Stmt]:
        is_default = any(child.type == "default" for child in node.children)
        lowered = self.statements.statement(declaration)
        if is_default:
            for statement in lowered:
                name = naming.defined_name(statement)
                if name is not None and name != "default":
                    self.state.links.alias("default", name)
        return lowered

    def _reexport(
        self, node: Syntax, source: Syntax, clause: Syntax | None
    ) -> list[m.Stmt]:
        pairs = _specifiers(clause) if clause is not None else []
        line, end = ts.span(node)
        module_text = literals.string_value(source)
        if clause is None:
            alias = _namespace_alias(node)
            if alias is None:
                return self._star_import(node, module_text)
            pairs.append(("*", alias))
        return self.state.links.import_of(line, end, module_text, pairs, node)

    def _star_import(self, node: Syntax, module_text: str) -> list[m.Stmt]:
        located = self.state.links.find(module_text)
        if located is None:
            return []
        line, end = ts.span(node)
        star = m.ImportName(line, end, "*")
        return [m.Import(line, end, located, [star], origin=node)]

    def _alias_locals(self, clause: Syntax) -> None:
        for exported, alias in _specifiers(clause):
            if alias != exported:
                self.state.links.alias(alias, exported)

    def _default(self, node: Syntax) -> list[m.Stmt]:
        value = node.child_by_field_name("value")
        if value is None:
            return []
        value = ts.unwrap(value)
        if value.type == "identifier":
            self.state.links.alias("default", ts.decode(value.text))
            return []
        if value.type in ts.FUNCTIONS:
            return [self.functions.function_def(value, "default", anchor=node)]
        if value.type == "class":
            return [self.classes.class_def(value, "default")]
        line, end = ts.span(node)
        return [
            m.Assign(
                line,
                end,
                [m.Name(line, end, "default", True, origin="default")],
                self.expressions.expr(value, "default"),
                None,
                "const",
                origin=node,
            )
        ]


def _specifiers(clause: Syntax) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for specifier in clause.named_children:
        if specifier.type != "export_specifier":
            continue
        exported = ts.decode(ts.field(specifier, "name").text)
        alias = specifier.child_by_field_name("alias")
        pairs.append((exported, ts.decode(alias.text) if alias else exported))
    return pairs


def _namespace_alias(node: Syntax) -> str | None:
    namespace = next(
        (c for c in node.named_children if c.type == "namespace_export"), None
    )
    alias = ts.first(namespace) if namespace is not None else None
    return ts.decode(alias.text) if alias is not None else None
