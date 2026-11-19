from collections.abc import Sequence

from tree_sitter import Node as Syntax

from turtlemap.analysis import model as m
from turtlemap.languages.javascript import nodes as ts
from turtlemap.languages.javascript.lowering.ports import (
    BindingsPort,
    ExpressionsPort,
    StatementsPort,
    TargetsPort,
)
from turtlemap.languages.javascript.lowering.state import LoweringState


class ControlFlow:
    bindings: BindingsPort
    expressions: ExpressionsPort
    statements: StatementsPort
    targets: TargetsPort

    def __init__(self, state: LoweringState) -> None:
        self.state = state

    def if_statement(self, node: Syntax) -> m.If:
        line, end = ts.span(node)
        alternative = node.child_by_field_name("alternative")
        orelse: list[m.Stmt] = []
        if alternative is not None:
            inner = ts.first(alternative)
            if inner is not None:
                orelse = (
                    [self.if_statement(inner)]
                    if inner.type == "if_statement"
                    else self.statements.body(inner)
                )
        return m.If(
            line,
            end,
            self.expressions.expr(ts.field(node, "condition")),
            self.statements.body(node.child_by_field_name("consequence")),
            orelse,
            origin=node,
        )

    def for_statement(self, node: Syntax) -> list[m.Stmt]:
        line, end = ts.span(node)
        out = self._initializer(node.child_by_field_name("initializer"))
        test = self._loop_test(node.child_by_field_name("condition"), line)
        body = self.statements.body(node.child_by_field_name("body"))
        increment = node.child_by_field_name("increment")
        if increment is not None:
            body = body + self.bindings.expression_statement(increment)
        out.append(m.While(line, end, test, body, origin=node))
        return out

    def for_in(self, node: Syntax) -> m.For:
        line, end = ts.span(node)
        left = ts.field(node, "left")
        right = ts.field(node, "right")
        is_async = any(child.type == "await" for child in node.children)
        target = self.targets.target(left)
        if node.child_by_field_name("kind") is not None:
            self.state.declare(target)
        return m.For(
            line,
            end,
            target,
            self.expressions.expr(right),
            self.statements.body(node.child_by_field_name("body")),
            is_async=is_async,
            origin=node,
        )

    def while_loop(self, node: Syntax) -> m.While:
        line, end = ts.span(node)
        return m.While(
            line,
            end,
            self.expressions.expr(ts.field(node, "condition")),
            self.statements.body(node.child_by_field_name("body")),
            origin=node,
        )

    def try_statement(self, node: Syntax) -> m.Try:
        line, end = ts.span(node)
        handler = node.child_by_field_name("handler")
        handlers = [self._handler(handler)] if handler is not None else []
        finalizer = node.child_by_field_name("finalizer")
        return m.Try(
            line,
            end,
            self.statements.body(node.child_by_field_name("body")),
            handlers,
            [],
            (
                self.statements.body(finalizer.child_by_field_name("body"))
                if finalizer
                else []
            ),
            origin=node,
        )

    def switch(self, node: Syntax) -> m.Match:
        line, end = ts.span(node)
        cases = _SwitchCases()
        body_node = node.child_by_field_name("body")
        for case in ts.named(body_node) if body_node is not None else []:
            if case.type in ("switch_case", "switch_default"):
                self._switch_case(case, cases)
        cases.close()
        return m.Match(
            line,
            end,
            self.expressions.expr(ts.field(node, "value")),
            cases.cases,
            origin=node,
        )

    def _initializer(self, initializer: Syntax | None) -> list[m.Stmt]:
        if initializer is None:
            return []
        if initializer.type in ts.DECLARATIONS:
            return self.bindings.declaration(initializer)
        if initializer.type == "expression_statement":
            inner = ts.first(initializer)
            return (
                self.bindings.expression_statement(inner) if inner is not None else []
            )
        if ts.is_expression(initializer):
            return self.bindings.expression_statement(initializer)
        return []

    def _loop_test(self, condition: Syntax | None, line: int) -> m.Expr:
        if condition is not None and condition.type == "expression_statement":
            condition = ts.first(condition)
        if condition is None:
            return m.Literal(line, line, True, origin="true")
        return self.expressions.expr(condition)

    def _handler(self, handler: Syntax) -> m.Handler:
        parameter = handler.child_by_field_name("parameter")
        body = self.statements.body(handler.child_by_field_name("body"))
        name: str | None = None
        if parameter is not None and parameter.type == "identifier":
            name = ts.decode(parameter.text)
        elif parameter is not None:
            name = "error"
            unpack = self._unpack_error(parameter, name)
            self.state.declare(unpack)
            body = [unpack, *body]
        if name is not None:
            self.state.declare_name(name)
        return m.Handler(*ts.span(handler), None, name, body, origin=handler)

    def _unpack_error(self, parameter: Syntax, name: str) -> m.Stmt:
        line, end = ts.span(parameter)
        return m.Assign(
            line,
            end,
            [self.targets.target(parameter)],
            m.Name(line, end, name, origin=name),
            origin=parameter,
        )

    def _switch_case(self, case: Syntax, cases: "_SwitchCases") -> None:
        cases.open(case)
        if case.type == "switch_default":
            cases.default = True
        else:
            value = case.child_by_field_name("value")
            if value is not None:
                cases.values.append(self.expressions.expr(value))
        statements = [
            child
            for child in case.children_by_field_name("body")
            if child.type not in ts.SKIPPED
        ]
        if statements:
            cases.add(case, self._case_body(statements))

    def _case_body(self, statements: Sequence[Syntax]) -> list[m.Stmt]:
        body = self.statements.block(statements)
        while body and isinstance(body[-1], m.Break):
            body.pop()
        return body


class _SwitchCases:
    def __init__(self) -> None:
        self.cases: list[m.Case] = []
        self.values: list[m.Expr] = []
        self.default = False
        self.first: Syntax | None = None

    def open(self, case: Syntax) -> None:
        self.first = self.first or case

    def add(self, case: Syntax, body: list[m.Stmt]) -> None:
        self.cases.append(self._case(body, case))
        self.values, self.default, self.first = [], False, None

    def close(self) -> None:
        if self.first is not None:
            self.cases.append(self._case([], self.first))

    def _case(self, body: list[m.Stmt], origin: Syntax) -> m.Case:
        assert self.first is not None
        line, end = ts.span(self.first)
        pattern = m.Pattern(line, end, [], self.default, self.values, origin=self.first)
        return m.Case(line, end, pattern, None, body, origin=origin)
