from collections.abc import Callable, Iterable, Sequence

from tree_sitter import Node as Syntax

from turtlemap.analysis import model as m
from turtlemap.languages.javascript import naming
from turtlemap.languages.javascript import nodes as ts
from turtlemap.languages.javascript.lowering.ports import (
    BindingsPort,
    ClassesPort,
    ControlFlowPort,
    ExportsPort,
    ExpressionsPort,
    FunctionsPort,
)
from turtlemap.languages.javascript.lowering.state import LoweringState

_Handler = Callable[[Syntax], list[m.Stmt]]
_Rows = list[tuple[Iterable[str], _Handler]]

_FUNCTION_DECLARATIONS = [
    "function_declaration",
    "generator_function_declaration",
    "function_signature",
]


class Statements:
    bindings: BindingsPort
    classes: ClassesPort
    control: ControlFlowPort
    exports: ExportsPort
    expressions: ExpressionsPort
    functions: FunctionsPort

    def __init__(self, state: LoweringState) -> None:
        self.state = state
        self._handlers = _first_wins(self._declaration_rows() + self._flow_rows())

    def block(self, nodes: Sequence[Syntax]) -> list[m.Stmt]:
        out: list[m.Stmt] = []
        for node in nodes:
            saved = self.state.hoisted
            self.state.hoisted = []
            lowered = self.statement(node)
            out.extend(self.state.hoisted)
            out.extend(lowered)
            self.state.hoisted = saved
        return out

    def body(self, node: Syntax | None) -> list[m.Stmt]:
        if node is None:
            return []
        if node.type == "statement_block":
            return self.block(ts.named(node))
        return self.block([node])

    def statement(self, node: Syntax) -> list[m.Stmt]:
        handler = self._handlers.get(node.type)
        if handler is not None:
            return handler(node)
        line, end = ts.span(node)
        return [
            m.OtherStmt(
                line,
                end,
                [
                    self.expressions.expr(child)
                    for child in ts.named(node)
                    if ts.is_expression(child)
                ],
                origin=node,
            )
        ]

    def _declaration_rows(self) -> _Rows:
        return [
            (["expression_statement"], self._expression_statement),
            (ts.DECLARATIONS, lambda node: self.bindings.declaration(node)),
            (_FUNCTION_DECLARATIONS, _single(self._function_declaration)),
            (ts.CLASSES, _single(self._class_declaration)),
            (
                ["interface_declaration"],
                _single(lambda node: self.classes.interface(node)),
            ),
            (["enum_declaration"], _single(lambda node: self.classes.enum(node))),
            (["type_alias_declaration"], lambda node: self.classes.type_alias(node)),
            (["import_statement"], self._import_statement),
            (["export_statement"], self._export_statement),
        ]

    def _flow_rows(self) -> _Rows:
        return [
            (["return_statement"], _single(self._return_statement)),
            (["throw_statement"], _single(self._throw_statement)),
            (["if_statement"], _single(lambda node: self.control.if_statement(node))),
            (["for_statement"], lambda node: self.control.for_statement(node)),
            (["for_in_statement"], _single(lambda node: self.control.for_in(node))),
            (
                ["while_statement", "do_statement"],
                _single(lambda node: self.control.while_loop(node)),
            ),
            (["try_statement"], _single(lambda node: self.control.try_statement(node))),
            (["switch_statement"], _single(lambda node: self.control.switch(node))),
            (
                ["break_statement"],
                _single(lambda node: m.Break(*ts.span(node), origin=node)),
            ),
            (
                ["continue_statement"],
                _single(lambda node: m.Continue(*ts.span(node), origin=node)),
            ),
            (["statement_block"], lambda node: self.block(ts.named(node))),
            (["labeled_statement"], _inside("body", self.statement)),
            (["empty_statement", "debugger_statement", "comment"], _nothing),
            (
                ["ambient_declaration", "module", "internal_module"],
                _inside("body", self.body),
            ),
        ]

    def _expression_statement(self, node: Syntax) -> list[m.Stmt]:
        inner = ts.first(node)
        return self.bindings.expression_statement(inner) if inner is not None else []

    def _import_statement(self, node: Syntax) -> list[m.Stmt]:
        self.state.links.mark_module()
        return self.state.links.import_statement(node)

    def _export_statement(self, node: Syntax) -> list[m.Stmt]:
        self.state.links.mark_module()
        return self.exports.statement(node)

    def _function_declaration(self, node: Syntax) -> m.Stmt:
        return self.functions.function_def(node, naming.name_text(node) or "default")

    def _class_declaration(self, node: Syntax) -> m.Stmt:
        return self.classes.class_def(node, naming.name_text(node) or "default")

    def _return_statement(self, node: Syntax) -> m.Stmt:
        value = ts.first(node)
        return m.Return(
            *ts.span(node),
            self.expressions.expr(value) if value is not None else None,
            origin=node,
        )

    def _throw_statement(self, node: Syntax) -> m.Stmt:
        value = ts.first(node)
        return m.Raise(
            *ts.span(node),
            self.expressions.expr(value) if value else None,
            origin=node,
        )

    def wrapper(self, call: Syntax, wrapped: Syntax) -> m.Expr:
        line, end = ts.span(call)
        arguments = ts.field(call, "arguments")
        return m.Call(
            line,
            end,
            self.expressions.expr(ts.field(call, "function")),
            [
                self.expressions.expr(argument)
                for argument in ts.named(arguments)
                if argument.id != wrapped.id
            ],
            origin=ts.field(call, "function"),
        )


def _first_wins(rows: _Rows) -> dict[str, _Handler]:
    handlers: dict[str, _Handler] = {}
    for kinds, handler in rows:
        for kind in kinds:
            handlers.setdefault(kind, handler)
    return handlers


def _single(lower: Callable[[Syntax], m.Stmt]) -> _Handler:
    return lambda node: [lower(node)]


def _inside(field: str, lower: _Handler) -> _Handler:
    def handle(node: Syntax) -> list[m.Stmt]:
        inner = node.child_by_field_name(field)
        return lower(inner) if inner is not None else []

    return handle


def _nothing(node: Syntax) -> list[m.Stmt]:
    return []
