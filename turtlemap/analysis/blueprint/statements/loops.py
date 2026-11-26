from collections.abc import Callable, Sequence

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.canvas import GraphNode
from turtlemap.analysis.blueprint.syntax import Form
from turtlemap.analysis.blueprint.code_shapes import flat_targets
from turtlemap.analysis.blueprint.statements.bindings import Bindings
from turtlemap.analysis.blueprint.statements.context import BuildContext
from turtlemap.analysis.blueprint.text import LABEL_LIMIT, shorten
from turtlemap.analysis.blueprint.values import BOOL, Value
from turtlemap.analysis.types import UNKNOWN

FIRST_SET_BY_LOOP = "first set by the loop"


class Loops:
    def __init__(
        self,
        context: BuildContext,
        bindings: Bindings,
        run: Callable[[Sequence[m.Stmt]], None],
    ) -> None:
        self.context = context
        self.bindings = bindings
        self.run = run

    def for_loop(self, statement: m.For) -> None:
        self.bindings.declare_ahead(statement, FIRST_SET_BY_LOOP)
        items = self.context.expressions.value(statement.iter, exec_candidate=True)
        targets = flat_targets(statement.target)
        names = ", ".join(self.bindings.target_label(target) for target in targets)
        source = shorten(self.context.text(statement.iter), LABEL_LIMIT)
        node = self._loop_node(
            f"For each {names} in {source}",
            statement.line,
            "async for" if statement.is_async else None,
        )
        self.context.graph.connect(node, "items", items)
        element = self.context.lookups.element(items) if len(targets) == 1 else UNKNOWN
        outputs = [
            self.context.graph.output(node, self.bindings.target_label(target), element)
            for target in targets
        ]
        self.context.flow.step(node)
        self._body(node, statement.body, list(zip(targets, outputs)), statement.line)
        self.run(statement.orelse)

    def while_loop(self, statement: m.While) -> None:
        self.bindings.declare_ahead(statement, FIRST_SET_BY_LOOP)
        condition = self.context.expressions.value(statement.test, exec_candidate=True)
        node = self._loop_node(
            f"While {shorten(self.context.text(statement.test), LABEL_LIMIT)}",
            statement.line,
        )
        self.context.graph.connect(node, "condition", condition, BOOL)
        self.context.flow.step(node)
        self._body(node, statement.body, [], statement.line)
        self.run(statement.orelse)

    def break_statement(self, statement: m.Break) -> None:
        self._jump("Break", statement.line)

    def continue_statement(self, statement: m.Continue) -> None:
        self._jump("Continue", statement.line)

    def _jump(self, title: str, line: int) -> None:
        node = self.context.graph.add("jump", title, line)
        node.form = Form("prefix", title.lower())
        self.context.flow.step(node)
        self.context.flow.resume([])

    def _loop_node(self, title: str, line: int, note: str | None = None) -> GraphNode:
        node = self.context.graph.add(
            "loop", title, line, exec_outs=["start"], note=note
        )
        node.exec_out = True
        return node

    def _body(
        self,
        node: GraphNode,
        body: Sequence[m.Stmt],
        targets: list[tuple[m.Expr, Value]],
        line: int,
    ) -> None:
        saved = dict(self.context.scope.env)
        self.context.flow.resume([(node, "start")])
        with self.context.graph.inside(node.id):
            for target, output in targets:
                self.bindings.bind(target, output, line)
            self.run(body)
        self.context.scope.restore(saved)
        self.context.flow.resume([(node, "then")])
