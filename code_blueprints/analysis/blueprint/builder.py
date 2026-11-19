from collections.abc import Callable, Sequence
from typing import Any, TypeVar
from code_blueprints.analysis.types import (
    UNKNOWN,
    TypeSystem,
)
from code_blueprints.analysis import model as m
from code_blueprints.analysis.workspace.parsed import ParsedFunction, ParsedModule
from code_blueprints.analysis.blueprint.values import Value
from code_blueprints.analysis.blueprint.canvas import (
    MAX_NODES,
    GraphFull,
)
from code_blueprints.analysis.blueprint.statements.context import BuildContext
from code_blueprints.analysis.blueprint.scope import Scope
from code_blueprints.analysis.blueprint.statements.bindings import Bindings
from code_blueprints.analysis.blueprint.statements.control import ControlFlow
from code_blueprints.analysis.blueprint.statements.entry import EntryNode
from code_blueprints.analysis.blueprint.statements.loops import Loops
from code_blueprints.analysis.blueprint.statements.closures import Closures

_Handler = tuple[type[m.Stmt], Callable[[m.Stmt], None]]
_Statement = TypeVar("_Statement", bound=m.Stmt)


def build_function_graph(
    types: TypeSystem, module: ParsedModule, function: ParsedFunction
) -> dict[str, Any]:
    return _FunctionGraphBuilder(BuildContext(types, module, function)).build()


class _FunctionGraphBuilder:
    def __init__(self, context: BuildContext) -> None:
        self.context = context
        self.bindings = Bindings(self.context)
        self.entry = EntryNode(self.context)
        self.control = ControlFlow(self.context, self.bindings, self._run_block)
        self.loops = Loops(self.context, self.bindings, self._run_block)
        self.closures = Closures(self.context, self.bindings, self._run_closure)
        self.context.expressions.nested = self.closures
        self._truncated = False
        self._handlers = self._statement_handlers()

    def build(self) -> dict[str, Any]:
        entry = self.entry.node()
        self.context.flow.resume([(entry, "then")])
        try:
            self._run_block(self.context.function.node.body)
        except GraphFull:
            self._mark_truncated()
        self.context.graph.strip_exec_when_only_returns(entry)
        graph = self.context.graph.to_json()
        self._native_labels(graph)
        if self._truncated:
            graph["truncated"] = True
        return graph

    def _mark_truncated(self) -> None:
        self._truncated = True
        last_line = (
            self.context.graph.nodes[-1].line
            if self.context.graph.nodes
            else self.context.function.node.line
        )
        tails = self.context.flow.tails
        frame = (
            (tails[0][0].id if tails[0][1] == "start" else tails[0][0].parent)
            if tails
            else None
        )
        with self.context.graph.inside(frame):
            marker = self.context.graph.add_unbounded(
                "return",
                "Truncated",
                last_line,
                note=f"Graph stopped after {MAX_NODES} nodes",
            )
        if any(node.exec_in or node.exec_out for node in self.context.graph.nodes):
            self.context.flow.step(marker)

    def _run_block(self, statements: Sequence[m.Stmt]) -> None:
        for statement in statements:
            self._statement(statement)

    def _run_closure(self, context: BuildContext) -> None:
        frame = context.frame
        assert frame is not None
        builder = _FunctionGraphBuilder(context)
        builder.entry.bind_parameters(frame)
        context.flow.resume([(frame, "start")])
        with context.graph.inside(frame.id):
            builder._run_block(context.function.node.body)
        context.graph.strip_exec_when_only_returns(frame)

    def _statement(self, statement: m.Stmt) -> None:
        try:
            self._dispatch_statement(statement)
        except GraphFull:
            raise
        except Exception as error:
            node = self.context.graph.add(
                "ext",
                self._source_title(statement),
                statement.line,
                note=f"Not drawn: {type(error).__name__}",
            )
            self.context.flow.step(node)

    def _dispatch_statement(self, statement: m.Stmt) -> None:
        for kind, handle in self._handlers:
            if isinstance(statement, kind):
                handle(statement)
                return
        self.context.flow.step(
            self.context.graph.add("ext", self._source_title(statement), statement.line)
        )

    def _statement_handlers(self) -> list[_Handler]:
        bindings, scope, flow = self.bindings, self.context.scope, self.context.flow
        control, loops = self.control, self.loops
        return [
            _handler(m.ExprStmt, lambda s: bindings.expression_statement(s.value)),
            _handler(m.Assign, lambda s: bindings.assign(s, exec_candidate=True)),
            _handler(m.AugAssign, bindings.augmented_assign),
            _handler(m.Return, bindings.return_statement),
            _handler(m.If, control.if_statement),
            _handler(m.For, loops.for_loop),
            _handler(m.While, loops.while_loop),
            _handler(m.With, self._with),
            _handler(m.Try, control.try_statement),
            _handler(m.Raise, control.raise_statement),
            _handler(m.Match, control.match),
            _handler(m.Assert, bindings.assert_statement),
            _handler(m.Delete, bindings.delete),
            _handler(m.Break, loops.break_statement),
            _handler(m.Continue, loops.continue_statement),
            _handler(m.Global, lambda s: scope.declare_globals(s.names)),
            _handler(m.FunctionDef, self.closures.define),
            _handler(m.ClassDef, lambda s: _define(scope, s)),
            _handler(m.Pass, lambda s: None),
            _handler(m.Import, lambda s: None),
        ]

    def _with(self, statement: m.With) -> None:
        contexts = [
            self.context.expressions.value(item.context) for item in statement.items
        ]
        title = ", ".join(self.context.text(item.context) for item in statement.items)
        node = self.context.graph.add(
            "ext",
            f"With {title}",
            statement.line,
            note="async with" if statement.is_async else None,
        )
        bindings: list[tuple[m.Expr, Value]] = []
        for item, context in zip(statement.items, contexts):
            self.context.graph.connect(node, "context", context)
            if item.target is not None:
                entered = context.type if isinstance(item.target, m.Name) else UNKNOWN
                bindings.append(
                    (
                        item.target,
                        self.context.graph.output(
                            node, self.bindings.target_label(item.target), entered
                        ),
                    )
                )
        self.context.flow.step(node)
        for target, value in bindings:
            self.bindings.bind(target, value, statement.line)
        self._run_block(statement.body)

    def _native_labels(self, graph: dict[str, Any]) -> None:
        labels = self.context.profile.literal_labels
        if not labels:
            return
        for node in graph.get("nodes", []):
            for pin in [*node.get("ins", []), *node.get("outs", [])]:
                kind = pin.get("type")
                if isinstance(kind, dict) and kind.get("label") in labels:
                    kind["label"] = labels[kind["label"]]

    def _source_title(self, statement: m.Stmt) -> str:
        text = self.context.text(statement)
        return text.splitlines()[0] if text else type(statement).__name__


def _handler(kind: type[_Statement], handle: Callable[[_Statement], None]) -> _Handler:
    def run(statement: m.Stmt) -> None:
        assert isinstance(statement, kind)
        handle(statement)

    return kind, run


def _define(scope: Scope, statement: m.ClassDef) -> None:
    scope.define_function(statement.cls.name)
    scope.forget(statement.cls.name)
