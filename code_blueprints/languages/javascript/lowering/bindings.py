from collections.abc import Callable

from tree_sitter import Node as Syntax
from code_blueprints.analysis import model as m
from code_blueprints.languages.javascript import nodes as ts
from code_blueprints.languages.javascript import naming
from code_blueprints.languages.javascript.annotations import TypeAnnotations
from code_blueprints.languages.javascript.lowering.state import LoweringState
from code_blueprints.languages.javascript.lowering.ports import (
    ClassesPort,
    ExpressionsPort,
    FunctionsPort,
    StatementsPort,
    TargetsPort,
)

_Form = Callable[[Syntax, int, int], list[m.Stmt] | None]


class Bindings:
    classes: ClassesPort
    expressions: ExpressionsPort
    functions: FunctionsPort
    statements: StatementsPort
    targets: TargetsPort
    types: TypeAnnotations

    def __init__(self, state: LoweringState) -> None:
        self.state = state
        self._statement_forms: dict[str, _Form] = {
            "assignment_expression": self._assignment,
            "augmented_assignment_expression": self._augmented,
            "update_expression": self._update,
            "unary_expression": self._delete,
            "call_expression": self._require,
        }

    def expression_statement(self, node: Syntax) -> list[m.Stmt]:
        line, end = ts.span(node)
        node = ts.unwrap(node)
        lower = self._statement_forms.get(node.type)
        lowered = lower(node, line, end) if lower is not None else None
        if lowered is not None:
            return lowered
        return [m.ExprStmt(line, end, self.expressions.expr(node), origin=node)]

    def _assignment(self, node: Syntax, line: int, end: int) -> list[m.Stmt] | None:
        targets: list[Syntax] = []
        current = node
        while current.type == "assignment_expression":
            targets.append(ts.field(current, "left"))
            current = ts.unwrap(ts.field(current, "right"))
        hoisted = self.hoisted_assignment(targets[-1], current)
        if hoisted is not None:
            return hoisted
        value = self.expressions.expr(current)
        assigned = [self.targets.target(target) for target in targets]
        return [m.Assign(line, end, assigned, value, origin=node)]

    def _augmented(self, node: Syntax, line: int, end: int) -> list[m.Stmt] | None:
        operator = ts.operator(node).removesuffix("=")
        return [
            m.AugAssign(
                line,
                end,
                self.targets.target(ts.field(node, "left")),
                ts.LOGICAL.get(operator, operator),
                self.expressions.expr(ts.field(node, "right")),
                origin=node,
            )
        ]

    def _update(self, node: Syntax, line: int, end: int) -> list[m.Stmt] | None:
        argument = ts.field(node, "argument")
        operator = "+" if "++" in ts.operator(node) else "-"
        one = m.Literal(line, end, 1, origin="1")
        target = self.targets.target(argument)
        return [m.AugAssign(line, end, target, operator, one, origin=node)]

    def _delete(self, node: Syntax, line: int, end: int) -> list[m.Stmt] | None:
        if ts.operator(node) != "delete":
            return None
        target = self.targets.target(ts.field(node, "argument"))
        return [m.Delete(line, end, [target], origin=node)]

    def _require(self, node: Syntax, line: int, end: int) -> list[m.Stmt] | None:
        return self.state.links.require_call(node, None)

    def hoisted_assignment(self, target: Syntax, value: Syntax) -> list[m.Stmt] | None:
        if value.type not in ts.FUNCTIONS or naming.is_expression_arrow(value):
            return None
        name = naming.last_segment(target)
        if name is None:
            return None
        function = self.functions.function_value(value, name)
        line, end = ts.span(target)
        return [
            m.Assign(line, end, [self.targets.target(target)], function, origin=target)
        ]

    def declaration(self, node: Syntax) -> list[m.Stmt]:
        kind = ts.keyword(node) or "var"
        out: list[m.Stmt] = []
        for declarator in node.named_children:
            if declarator.type != "variable_declarator":
                continue
            out.extend(self.declarator(declarator, kind))
        for statement in out:
            self._declare(statement)
        return out

    def _declare(self, statement: m.Stmt) -> None:
        if isinstance(statement, m.Assign):
            for target in statement.targets:
                self.state.declare(target)
        elif isinstance(statement, m.Import):
            for imported in statement.names:
                self.state.declare_name(imported.alias or imported.name)

    def declarator(self, node: Syntax, kind: str) -> list[m.Stmt]:
        line, end = ts.span(node)
        name_node = ts.field(node, "name")
        value_node = node.child_by_field_name("value")
        value = ts.unwrap(value_node) if value_node is not None else None
        type_node = node.child_by_field_name("type")
        annotation = self.types.annotation(type_node)
        if value is not None and name_node.type == "identifier":
            name = ts.decode(name_node.text)
            if value.type in ts.FUNCTIONS:
                return [self.functions.function_def(value, name, anchor=node.parent)]
            if value.type == "class":
                return [self.classes.class_def(value, name)]
            wrapped = naming.wrapped_function(value)
            if wrapped is not None:
                return [
                    self.functions.function_def(
                        wrapped,
                        name,
                        anchor=node.parent,
                        decorators=[self.statements.wrapper(value, wrapped)],
                    )
                ]
        if value is not None and value.type == "call_expression":
            imported = self.state.links.require_call(value, name_node)
            if imported is not None:
                return imported
        lowered: m.Expr
        if value is None:
            lowered = m.Literal(line, end, None, origin="undefined")
        else:
            context = (
                ts.decode(name_node.text) if name_node.type == "identifier" else None
            )
            lowered = self.expressions.expr(value, context)
        return [
            m.Assign(
                line,
                end,
                [self.targets.target(name_node)],
                lowered,
                annotation,
                kind,
                origin=node,
            )
        ]
