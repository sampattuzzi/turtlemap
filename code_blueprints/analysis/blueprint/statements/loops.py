from collections.abc import Callable, Sequence

from code_blueprints.analysis import model as m
from code_blueprints.analysis.blueprint.canvas import GraphNode
from code_blueprints.analysis.blueprint.code_shapes import flat_targets
from code_blueprints.analysis.blueprint.statements.bindings import Bindings
from code_blueprints.analysis.blueprint.statements.context import BuildContext
from code_blueprints.analysis.blueprint.values import BOOL
from code_blueprints.analysis.types import UNKNOWN


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
        items = self.context.expressions.value(statement.iter, exec_candidate=True)
        targets = flat_targets(statement.target)
        title = ", ".join(self.bindings.target_label(target) for target in targets)
        node = self.context.graph.add(
            "loop",
            f"For each {title}",
            statement.line,
            exec_outs=["Loop body", "Completed"],
            note="async for" if statement.is_async else None,
        )
        self.context.graph.connect(node, "items", items)
        element = self.context.lookups.element(items) if len(targets) == 1 else UNKNOWN
        outputs = [
            self.context.graph.output(node, self.bindings.target_label(target), element)
            for target in targets
        ]
        self.context.flow.step(node)
        for target, output in zip(targets, outputs):
            if isinstance(target, m.Name):
                self.context.scope.bind(target.id, output)
            else:
                self.bindings.bind(target, output, statement.line)
        self._loop_body(node, statement.body, statement.orelse)

    def while_loop(self, statement: m.While) -> None:
        if self.context.expressions.folding.folds(statement.test, named=True):
            node = self.context.expressions.folding.inline_condition(
                statement.test,
                lambda: self.context.graph.add(
                    "loop",
                    "While",
                    statement.line,
                    exec_outs=["Loop body", "Completed"],
                ),
            )
        else:
            condition = self.context.expressions.value(statement.test)
            node = self.context.graph.add(
                "loop",
                f"While {self.context.text(statement.test)}",
                statement.line,
                exec_outs=["Loop body", "Completed"],
            )
            self.context.graph.connect(node, "condition", condition, BOOL)
        self.context.flow.step(node)
        self._loop_body(node, statement.body, statement.orelse)

    def break_statement(self, statement: m.Break) -> None:
        if self.context.loop_exits:
            self.context.loop_exits[-1].extend(self.context.flow.tails)
        self.context.flow.resume([])

    def _loop_body(
        self, node: GraphNode, body: Sequence[m.Stmt], orelse: Sequence[m.Stmt]
    ) -> None:
        carried = self.context.carried
        self.context.carried = carried | frozenset(self.context.scope.env)
        self.context.loop_exits.append([])
        self.context.flow.resume([(node, "Loop body")])
        try:
            self.run(body)
        finally:
            exits = self.context.loop_exits.pop()
            self.context.carried = carried
        self.context.flow.resume([(node, "Completed")])
        self.run(orelse)
        self.context.flow.resume(self.context.flow.tails + exits)
