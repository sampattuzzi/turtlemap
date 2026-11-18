import ast
import sys
from collections.abc import Callable, Iterator, Sequence

from code_blueprints.analysis import model as m
from code_blueprints.languages.language import (
    ImportBinding,
)
from code_blueprints.languages.python.definitions import DefinitionLowering
from code_blueprints.languages.python.expressions import ExpressionLowering
from code_blueprints.languages.python.imports import ImportLowering
from code_blueprints.languages.python.nodes import on, span
from code_blueprints.languages.python.operators import BINARY

_StatementRow = tuple[type[ast.AST], Callable[[ast.AST], m.Stmt]]


class Lowering:
    def __init__(self, package: str) -> None:
        self.imports: dict[str, ImportBinding] = {}
        self.expressions = ExpressionLowering()
        self.definitions = DefinitionLowering(self.expressions, self.block)
        self.imported = ImportLowering(package)
        self._handlers = dict(self._simple_statements() + self._compound_statements())

    def block(self, statements: Sequence[ast.stmt]) -> list[m.Stmt]:
        return [self.statement(statement) for statement in statements]

    def statement(self, node: ast.stmt) -> m.Stmt:
        handler = self._handlers.get(type(node))
        if handler is not None:
            return handler(node)
        line, end = span(node)
        return m.OtherStmt(line, end, origin=node)

    def _simple_statements(self) -> list[_StatementRow]:
        rows = [
            on(ast.Expr, self._from_expr),
            on(ast.Assign, self._from_assign),
            on(ast.AnnAssign, self._from_ann_assign),
            on(ast.AugAssign, self._from_aug_assign),
            on(ast.Return, self._from_return),
            on(ast.Raise, self._from_raise),
            on(ast.Assert, self._from_assert),
            on(ast.Delete, self._from_delete),
            on(ast.Break, _from_break),
            on(ast.Continue, _from_continue),
            on(ast.Pass, _from_pass),
            on(ast.Global, _from_global),
            on(ast.Nonlocal, _from_global),
            on(ast.Import, self.imported.import_statement),
            on(ast.ImportFrom, self.imported.import_from),
        ]
        if sys.version_info >= (3, 12):
            rows.append(on(ast.TypeAlias, _from_pass))
        return rows

    def _compound_statements(self) -> list[_StatementRow]:
        return [
            on(ast.If, self._from_if),
            on(ast.For, self._from_for_or_async_for),
            on(ast.AsyncFor, self._from_for_or_async_for),
            on(ast.While, self._from_while),
            on(ast.With, self._from_with_or_async_with),
            on(ast.AsyncWith, self._from_with_or_async_with),
            on(ast.Try, self._from_try_or_try_star),
            on(ast.TryStar, self._from_try_or_try_star),
            on(ast.Match, self._from_match),
            on(ast.FunctionDef, self.definitions.function_def),
            on(ast.AsyncFunctionDef, self.definitions.function_def),
            on(ast.ClassDef, self.definitions.class_def),
        ]

    def _from_expr(self, node: ast.Expr, line: int, end: int) -> m.Stmt:
        return m.ExprStmt(line, end, self.expressions.expr(node.value), origin=node)

    def _from_return(self, node: ast.Return, line: int, end: int) -> m.Stmt:
        value = self.expressions.optional(node.value)
        return m.Return(line, end, value, origin=node)

    def _from_assign(self, node: ast.Assign, line: int, end: int) -> m.Stmt:
        return m.Assign(
            line,
            end,
            [self.expressions.expr(target) for target in node.targets],
            self.expressions.expr(node.value),
            origin=node,
        )

    def _from_ann_assign(self, node: ast.AnnAssign, line: int, end: int) -> m.Stmt:
        return m.Assign(
            line,
            end,
            [self.expressions.expr(node.target)],
            self.expressions.optional(node.value),
            annotation=self.expressions.signatures.type_expr(node.annotation),
            origin=node,
        )

    def _from_aug_assign(self, node: ast.AugAssign, line: int, end: int) -> m.Stmt:
        return m.AugAssign(
            line,
            end,
            self.expressions.expr(node.target),
            BINARY.get(type(node.op), "?"),
            self.expressions.expr(node.value),
            origin=node,
        )

    def _from_if(self, node: ast.If, line: int, end: int) -> m.Stmt:
        return m.If(
            line,
            end,
            self.expressions.expr(node.test),
            self.block(node.body),
            self.block(node.orelse),
            origin=node,
        )

    def _from_for_or_async_for(
        self, node: ast.For | ast.AsyncFor, line: int, end: int
    ) -> m.Stmt:
        return m.For(
            line,
            end,
            self.expressions.expr(node.target),
            self.expressions.expr(node.iter),
            self.block(node.body),
            self.block(node.orelse),
            is_async=isinstance(node, ast.AsyncFor),
            origin=node,
        )

    def _from_while(self, node: ast.While, line: int, end: int) -> m.Stmt:
        return m.While(
            line,
            end,
            self.expressions.expr(node.test),
            self.block(node.body),
            self.block(node.orelse),
            origin=node,
        )

    def _from_with_or_async_with(
        self, node: ast.With | ast.AsyncWith, line: int, end: int
    ) -> m.Stmt:
        return m.With(
            line,
            end,
            [
                m.WithItem(
                    *span(item.context_expr),
                    self.expressions.expr(item.context_expr),
                    self.expressions.optional(item.optional_vars),
                    origin=item,
                )
                for item in node.items
            ],
            self.block(node.body),
            is_async=isinstance(node, ast.AsyncWith),
            origin=node,
        )

    def _from_try_or_try_star(
        self, node: ast.Try | ast.TryStar, line: int, end: int
    ) -> m.Stmt:
        return m.Try(
            line,
            end,
            self.block(node.body),
            [
                m.Handler(
                    *span(handler),
                    self.expressions.optional(handler.type),
                    handler.name,
                    self.block(handler.body),
                    origin=handler,
                )
                for handler in node.handlers
            ],
            self.block(node.orelse),
            self.block(node.finalbody),
            origin=node,
        )

    def _from_raise(self, node: ast.Raise, line: int, end: int) -> m.Stmt:
        return m.Raise(
            line,
            end,
            self.expressions.optional(node.exc),
            self.expressions.optional(node.cause),
            origin=node,
        )

    def _from_assert(self, node: ast.Assert, line: int, end: int) -> m.Stmt:
        return m.Assert(
            line,
            end,
            self.expressions.expr(node.test),
            self.expressions.optional(node.msg),
            origin=node,
        )

    def _from_delete(self, node: ast.Delete, line: int, end: int) -> m.Stmt:
        return m.Delete(
            line,
            end,
            [self.expressions.expr(target) for target in node.targets],
            origin=node,
        )

    def _from_match(self, node: ast.Match, line: int, end: int) -> m.Stmt:
        return m.Match(
            line,
            end,
            self.expressions.expr(node.subject),
            [
                m.Case(
                    *span(case.pattern),
                    m.Pattern(
                        *span(case.pattern),
                        _pattern_captures(case.pattern),
                        isinstance(case.pattern, ast.MatchAs)
                        and case.pattern.pattern is None,
                        [
                            self.expressions.expr(reference)
                            for reference in _pattern_references(case.pattern)
                        ],
                        origin=case.pattern,
                    ),
                    self.expressions.optional(case.guard),
                    self.block(case.body),
                    origin=case,
                )
                for case in node.cases
            ],
            origin=node,
        )


def _pattern_references(pattern: ast.pattern) -> Iterator[ast.expr]:
    for node in ast.walk(pattern):
        if isinstance(node, ast.pattern):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.expr):
                    yield child


def _pattern_captures(pattern: ast.pattern) -> list[str]:
    names: list[str] = []
    for node in ast.walk(pattern):
        if (
            isinstance(node, (ast.MatchAs, ast.MatchStar))
            and node.name
            and node.name not in names
        ):
            names.append(node.name)
        elif (
            isinstance(node, ast.MatchMapping) and node.rest and node.rest not in names
        ):
            names.append(node.rest)
    return names


def _from_break(node: ast.Break, line: int, end: int) -> m.Stmt:
    return m.Break(line, end, origin=node)


def _from_continue(node: ast.Continue, line: int, end: int) -> m.Stmt:
    return m.Continue(line, end, origin=node)


def _from_pass(node: ast.stmt, line: int, end: int) -> m.Stmt:
    return m.Pass(line, end, origin=node)


def _from_global(node: ast.Global | ast.Nonlocal, line: int, end: int) -> m.Stmt:
    return m.Global(line, end, list(node.names), origin=node)
