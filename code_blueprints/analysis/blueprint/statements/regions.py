from collections.abc import Sequence
from dataclasses import dataclass
from code_blueprints.analysis import model as m
from code_blueprints.analysis.blueprint.values import Value, Folded
from code_blueprints.analysis.blueprint.code_shapes import assigned_names
from code_blueprints.analysis.blueprint.scope import merge
from code_blueprints.analysis.blueprint.code_shapes import (
    contains_return,
    always_terminates,
)
from code_blueprints.analysis.blueprint.statements.context import BuildContext
from code_blueprints.analysis.blueprint.statements.bindings import Bindings


@dataclass(frozen=True)
class _Outcome:
    value: Value | None
    terminated: bool


class DataRegions:
    def __init__(self, context: BuildContext, bindings: Bindings) -> None:
        self.context = context
        self.bindings = bindings

    def merge_if(self, statement: m.If) -> None:
        condition = self.context.expressions.value(statement.test)
        saved = dict(self.context.scope.env)
        self.data_block(statement.body)
        true_env = self.context.scope.env
        self.context.scope.restore(dict(saved))
        self.data_block(statement.orelse)
        self.context.scope.restore(
            merge(condition, true_env, self.context.scope.env, statement.line)
        )

    def starts_return_region(
        self, statements: Sequence[m.Stmt], *, function_level: bool
    ) -> bool:
        if not contains_return(statements[:1]) or not self.is_data_block(statements):
            return False
        return function_level or always_terminates(statements)

    def return_region(self, statements: Sequence[m.Stmt]) -> None:
        outcome = self.data_block(statements)
        value = (
            outcome.value
            if outcome.terminated and outcome.value is not None
            else self.context.lookups.none_literal()
        )
        self.bindings.emit_return(value, statements[-1].line)

    def data_block(self, statements: Sequence[m.Stmt]) -> _Outcome:
        for index, statement in enumerate(statements):
            if isinstance(statement, m.Return):
                value = (
                    self.context.expressions.value(statement.value)
                    if statement.value is not None
                    else self.context.lookups.none_literal()
                )
                return _Outcome(value, True)
            if isinstance(statement, m.If):
                outcome = self._data_if(statement, statements[index + 1 :])
                if outcome is not None:
                    return outcome
            elif isinstance(statement, m.Assign):
                self.bindings.assign(statement, exec_candidate=False)
        return _Outcome(None, False)

    def _data_if(self, statement: m.If, rest: Sequence[m.Stmt]) -> _Outcome | None:
        condition: Value | Folded = (
            self.context.expressions.folding.fold(statement.test)
            if self.context.expressions.folding.folds(statement.test, named=True)
            else self.context.expressions.value(statement.test)
        )
        saved = dict(self.context.scope.env)
        when_true = self.data_block(statement.body)
        true_env = self.context.scope.env
        self.context.scope.restore(dict(saved))
        when_false = self.data_block(statement.orelse)
        if when_true.terminated and when_false.terminated:
            return _Outcome(
                self.context.expressions.folding.select_on(
                    condition,
                    self._returned(when_true),
                    self._returned(when_false),
                    statement.line,
                ),
                True,
            )
        if not when_true.terminated and not when_false.terminated:
            if isinstance(condition, Folded):
                condition = self.context.expressions.folding.node(
                    condition, "Check", statement.line
                )
            self.context.scope.restore(
                merge(condition, true_env, self.context.scope.env, statement.line)
            )
            return None
        if when_false.terminated:
            self.context.scope.restore(true_env)
        continuation = self.data_block(rest)
        later = self._returned(continuation)
        if when_true.terminated:
            return _Outcome(
                self.context.expressions.folding.select_on(
                    condition, self._returned(when_true), later, statement.line
                ),
                True,
            )
        return _Outcome(
            self.context.expressions.folding.select_on(
                condition, later, self._returned(when_false), statement.line
            ),
            True,
        )

    def is_data_block(self, statements: Sequence[m.Stmt]) -> bool:
        return all(self._is_data_statement(statement) for statement in statements)

    def _is_data_statement(self, statement: m.Stmt) -> bool:
        if isinstance(statement, m.Pass) or (
            isinstance(statement, m.ExprStmt) and isinstance(statement.value, m.Literal)
        ):
            return True
        if isinstance(statement, m.Return):
            return statement.value is None or not _suspends(statement.value)
        if isinstance(statement, m.Assign):
            return self._is_data_assignment(statement)
        if isinstance(statement, m.If):
            return (
                not _suspends(statement.test)
                and self.is_data_block(statement.body)
                and self.is_data_block(statement.orelse)
            )
        return False

    def _is_data_assignment(self, statement: m.Assign) -> bool:
        names = [
            name
            for target in statement.targets
            for name in (assigned_names(target) or ["."])
        ]
        if any(self._escapes(name) for name in names):
            return False
        value = statement.value
        return value is None or (
            not _suspends(value) and not self._is_effectful_call(value)
        )

    def _escapes(self, name: str) -> bool:
        return (
            name.startswith("*")
            or name == "."
            or name in self.context.carried
            or name in self.context.scope.declared_globals
        )

    def _is_effectful_call(self, value: m.Expr) -> bool:
        return isinstance(value, m.Call) and not self.context.calls.call_is_pure(value)

    def _returned(self, outcome: _Outcome) -> Value:
        return (
            outcome.value
            if outcome.terminated and outcome.value is not None
            else self.context.lookups.none_literal()
        )


def _suspends(expression: m.Expr) -> bool:
    return any(
        isinstance(node, (m.Await, m.Yield, m.AssignExpr))
        for node in m.walk(expression)
    )
