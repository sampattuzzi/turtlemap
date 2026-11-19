from collections.abc import Callable, Sequence
from dataclasses import dataclass

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.canvas import GraphNode, Tail
from turtlemap.analysis.blueprint.code_shapes import contains_return
from turtlemap.analysis.blueprint.scope import merge
from turtlemap.analysis.blueprint.statements.context import BuildContext
from turtlemap.analysis.blueprint.statements.regions import DataRegions
from turtlemap.analysis.blueprint.text import LABEL_LIMIT, short_name, shorten
from turtlemap.analysis.blueprint.values import BOOL, Environment, Value
from turtlemap.analysis.types import UNKNOWN


class ControlFlow:
    def __init__(
        self,
        context: BuildContext,
        regions: DataRegions,
        run: Callable[[Sequence[m.Stmt]], None],
    ) -> None:
        self.context = context
        self.regions = regions
        self.run = run

    def if_statement(self, statement: m.If) -> None:
        if self.regions.is_data_block([statement]) and not contains_return([statement]):
            self.regions.merge_if(statement)
        else:
            self._branch_if(statement)

    def _branch_if(self, statement: m.If) -> None:
        node, condition = self._branch_node(statement)
        self.context.flow.step(node)
        saved = dict(self.context.scope.env)
        true_arm = self._arm(node, "True", statement.body)
        self.context.scope.restore(dict(saved))
        false_arm = self._arm(node, "False", statement.orelse)
        self.context.flow.resume(true_arm.tails + false_arm.tails)
        if not true_arm.tails and false_arm.tails:
            self.context.scope.restore(false_arm.env)
        elif true_arm.tails and not false_arm.tails:
            self.context.scope.restore(true_arm.env)
        else:
            if condition is None:
                condition = (
                    self.context.graph.output(node, "condition", BOOL)
                    if _differ(true_arm.env, false_arm.env)
                    else Value(BOOL)
                )
            self.context.scope.restore(
                merge(condition, true_arm.env, false_arm.env, statement.line)
            )

    def _branch_node(self, statement: m.If) -> tuple[GraphNode, Value | None]:
        if self.context.expressions.folding.folds(statement.test, named=True):
            node = self.context.expressions.folding.inline_condition(
                statement.test,
                lambda: self.context.graph.add(
                    "branch", "Branch", statement.line, exec_outs=["True", "False"]
                ),
            )
            return node, None
        condition = self.context.expressions.value(statement.test, exec_candidate=True)
        node = self.context.graph.add(
            "branch", "Branch", statement.line, exec_outs=["True", "False"]
        )
        self.context.graph.connect(node, "condition", condition, BOOL)
        return node, condition

    def _arm(self, node: GraphNode, label: str, body: Sequence[m.Stmt]) -> "_Arm":
        self.context.flow.resume([(node, label)])
        self.run(body)
        return _Arm(self.context.flow.tails, self.context.scope.env)

    def try_statement(self, statement: m.Try) -> None:
        labels = self._try_labels(statement)
        node = self.context.graph.add(
            "branch",
            "Try",
            statement.line,
            exec_outs=labels,
            note="finally runs afterwards" if statement.finalbody else None,
        )
        branches = node.exec_outs or labels
        self.context.flow.step(node)
        saved = dict(self.context.scope.env)
        self.context.flow.resume([(node, branches[0])])
        self.run(statement.body)
        self.run(statement.orelse)
        tails, env = self._run_handlers(statement, node, branches[1:], saved)
        self.context.flow.resume(tails)
        self.context.scope.restore(env)
        if statement.finalbody and not tails:
            self.context.flow.resume([(node, "Finally")])
            self.run(statement.finalbody)
            self.context.flow.resume([])
            return
        self.run(statement.finalbody)

    def _try_labels(self, statement: m.Try) -> list[str]:
        word = self.context.profile.handler_word
        return [
            "Try",
            *(
                (
                    f"{word} {self.context.text(handler.type)}"
                    if handler.type is not None
                    else word
                )
                for handler in statement.handlers
            ),
        ]

    def _run_handlers(
        self,
        statement: m.Try,
        node: GraphNode,
        labels: Sequence[str],
        saved: Environment,
    ) -> tuple[list[Tail], Environment]:
        tails: list[Tail] = self.context.flow.tails
        env: Environment = self.context.scope.env
        for handler, label in zip(statement.handlers, labels):
            self.context.scope.restore(dict(saved))
            if handler.name:
                caught = self.context.lookups.exception(handler.type)
                self.context.scope.bind(
                    handler.name, self.context.graph.output(node, handler.name, caught)
                )
            self.context.flow.resume([(node, label)])
            self.run(handler.body)
            tails = tails + self.context.flow.tails
            env = {**self.context.scope.env, **env}
        return tails, env

    def raise_statement(self, statement: m.Raise) -> None:
        node = self._raise_node(statement.exc, statement.line)
        if statement.cause is not None:
            self.context.graph.connect(
                node, "cause", self.context.expressions.value(statement.cause)
            )
        self.context.flow.step(node)
        self.context.flow.resume([])

    def _raise_node(self, exception: m.Expr | None, line: int) -> GraphNode:
        if exception is None:
            return self.context.graph.add("raise", "Re-raise", line)
        if isinstance(exception, m.Call) and self._raises_class(exception):
            return self._raise_class(exception, line)
        value = self.context.expressions.value(exception)
        title = (
            f"Raise {short_name(self.context.text(exception))}"
            if value.literal is not None
            else "Raise"
        )
        node = self.context.graph.add(
            "raise",
            title,
            line,
            target=value.type.ref if value.literal is not None else None,
        )
        if value.literal is None:
            self.context.graph.connect(node, "error", value)
        return node

    def _raise_class(self, exception: m.Call, line: int) -> GraphNode:
        callee = self.context.calls.resolve_callee(exception)
        arguments = self.context.calls.arguments(
            exception, callee, first_fallback="message"
        )
        name = short_name(callee.title.removeprefix("Make "))
        node = self.context.graph.add(
            "raise",
            f"Raise {name}",
            line,
            target=callee.target,
            external=callee.external,
        )
        self.context.calls.connect_arguments(node, arguments)
        return node

    def _raises_class(self, call: m.Call) -> bool:
        name = m.dotted_name(call.func)
        if name is None or self.context.scope.is_local(name.split(".")[0]):
            return False
        last = name.rsplit(".", 1)[-1]
        return last[:1].isupper()

    def match(self, statement: m.Match) -> None:
        subject = self.context.expressions.value(statement.subject, exec_candidate=True)
        labels = [self._case_label(case) for case in statement.cases]
        exhaustive = any(
            case.pattern.catch_all and case.guard is None for case in statement.cases
        )
        node = self.context.graph.add(
            "branch",
            f"{self.context.profile.match_title} {self.context.text(statement.subject)}",
            statement.line,
            exec_outs=labels if exhaustive else [*labels, "No match"],
        )
        branches = node.exec_outs or labels
        self.context.graph.connect(node, "subject", subject)
        self.context.flow.step(node)
        saved = dict(self.context.scope.env)
        tails: list[Tail] = [] if exhaustive else [(node, branches[-1])]
        env: Environment = dict(saved)
        for case, label in zip(statement.cases, branches):
            tails = tails + self._run_case(case, node, label, saved)
            env.update(self.context.scope.env)
        self.context.flow.resume(tails)
        self.context.scope.restore(env)

    def _case_label(self, case: m.Case) -> str:
        guard = f" if {self.context.text(case.guard)}" if case.guard else ""
        return shorten(
            self.context.language.case_label(case.pattern) + guard, LABEL_LIMIT
        )

    def _run_case(
        self, case: m.Case, node: GraphNode, label: str, saved: Environment
    ) -> list[Tail]:
        self.context.scope.restore(dict(saved))
        for name in case.pattern.captures:
            self.context.scope.bind(
                name, self.context.graph.output(node, name, UNKNOWN)
            )
        if case.guard is not None:
            self.context.expressions.value(case.guard)
        self.context.flow.resume([(node, label)])
        self.run(case.body)
        return self.context.flow.tails


@dataclass(frozen=True)
class _Arm:
    tails: list[Tail]
    env: Environment


def _differ(true_env: Environment, false_env: Environment) -> bool:
    return any(
        name in false_env and true_env[name] != false_env[name] for name in true_env
    )
