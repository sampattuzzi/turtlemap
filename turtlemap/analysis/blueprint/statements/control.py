from collections.abc import Callable, Sequence

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.canvas import GraphNode, Tail
from turtlemap.analysis.blueprint.syntax import Form, call
from turtlemap.analysis.blueprint.statements.bindings import Bindings
from turtlemap.analysis.blueprint.statements.context import BuildContext
from turtlemap.analysis.blueprint.text import LABEL_LIMIT, short_name, shorten
from turtlemap.analysis.blueprint.values import BOOL, Environment, Value
from turtlemap.analysis.types import UNKNOWN

FIRST_SET_BY_BRANCH = "first set by the branch"


CONDITION_LIMIT = 80


class ControlFlow:
    def __init__(
        self,
        context: BuildContext,
        bindings: Bindings,
        run: Callable[[Sequence[m.Stmt]], None],
    ) -> None:
        self.context = context
        self.bindings = bindings
        self.run = run

    def if_statement(self, statement: m.If) -> None:
        arms = _arms(statement)
        self.bindings.declare_ahead(statement, FIRST_SET_BY_BRANCH)
        conditions = [
            self._condition(test, first=index == 0) if test is not None else None
            for index, (test, _) in enumerate(arms)
        ]
        branch = self.context.graph.add("branch", "Branch", statement.line)
        self.context.flow.step(branch)
        lanes: list[tuple[GraphNode, Sequence[m.Stmt]]] = []
        earlier: list[str] = []
        for index, ((test, body), condition) in enumerate(zip(arms, conditions)):
            lane = self._lane(branch, self._word(index, test), statement.line)
            if test is not None and condition is not None:
                text = self._condition_text(test)
                self._show_condition(lane, condition, text)
                lane.reach = f"{lane.title} {text}"
                earlier.append(text)
            else:
                lane.reach = f"{lane.title} · " + self.context.profile.conjunction.join(
                    self.context.profile.negation.format(text) for text in earlier
                )
            lanes.append((lane, body))
        self._run_lanes(branch, lanes, falls_through=arms[-1][0] is not None)

    def _condition(self, test: m.Expr, *, first: bool) -> Value:
        return self.context.expressions.value(test, exec_candidate=first)

    def _show_condition(self, lane: GraphNode, condition: Value, text: str) -> None:
        lane.expression = [text]
        self.context.graph.connect(lane, text, condition, BOOL)

    def _condition_text(self, test: m.Expr) -> str:
        return shorten(" ".join(self.context.text(test).split()), CONDITION_LIMIT)

    def _word(self, index: int, test: m.Expr | None) -> str:
        profile = self.context.profile
        if test is None:
            return profile.else_word
        return profile.if_word if index == 0 else profile.elif_word

    def _lane(self, branch: GraphNode, title: str, line: int) -> GraphNode:
        with self.context.graph.inside(branch.id):
            return self.context.graph.add("lane", title, line, exec_outs=["start"])

    def _run_lanes(
        self,
        branch: GraphNode,
        lanes: Sequence[tuple[GraphNode, Sequence[m.Stmt]]],
        *,
        falls_through: bool,
        bind: Callable[[GraphNode, int], None] = lambda lane, index: None,
    ) -> None:
        saved = dict(self.context.scope.env)
        finished = falls_through
        for index, (lane, body) in enumerate(lanes):
            self.context.scope.restore(dict(saved))
            self.context.flow.resume([(lane, "start")])
            with self.context.graph.inside(lane.id):
                bind(lane, index)
                self.run(body)
            finished = finished or bool(self.context.flow.tails)
        self.context.scope.restore(saved)
        branch.exec_out = finished
        self.context.flow.resume([(branch, "then")] if finished else [])

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
            node = self.context.graph.add("raise", "Re-raise", line)
            node.form = Form("prefix", "raise")
            return node
        if isinstance(exception, m.Call) and self._raises_class(exception):
            return self._raise_class(exception, line)
        value = self.context.expressions.value(exception)
        name = short_name(self.context.text(exception))
        title = f"Raise {name}" if value.literal is not None else "Raise"
        node = self.context.graph.add(
            "raise",
            title,
            line,
            target=value.type.ref if value.literal is not None else None,
        )
        node.form = (
            Form("prefix", f"raise {name}")
            if value.literal is not None
            else Form("ending", "raise")
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
        node.form = call(f"raise {name}")
        self.context.calls.connect_arguments(node, arguments)
        return node

    def _raises_class(self, call: m.Call) -> bool:
        name = m.dotted_name(call.func)
        if name is None or self.context.scope.is_local(name.split(".")[0]):
            return False
        last = name.rsplit(".", 1)[-1]
        return last[:1].isupper()

    def match(self, statement: m.Match) -> None:
        self.bindings.declare_ahead(statement, FIRST_SET_BY_BRANCH)
        subject = self.context.expressions.value(statement.subject, exec_candidate=True)
        subject_text = self._condition_text(statement.subject)
        exhaustive = any(
            case.pattern.catch_all and case.guard is None for case in statement.cases
        )
        branch = self.context.graph.add(
            "branch",
            f"{self.context.profile.match_title} {subject_text}",
            statement.line,
        )
        self.context.graph.connect(branch, "subject", subject)
        self.context.flow.step(branch)
        lanes: list[tuple[GraphNode, Sequence[m.Stmt]]] = []
        for case in statement.cases:
            lane = self._lane(branch, self._case_label(case), case.line)
            lane.reach = f"{branch.title} · {lane.title}"
            lanes.append((lane, case.body))

        def bind(lane: GraphNode, index: int) -> None:
            case = statement.cases[index]
            for name in case.pattern.captures:
                self.bindings.assign_name(
                    name,
                    self.context.graph.output(lane, name, UNKNOWN),
                    case.line,
                )
            if case.guard is not None:
                self.context.expressions.value(case.guard)

        self._run_lanes(branch, lanes, falls_through=not exhaustive, bind=bind)

    def _case_label(self, case: m.Case) -> str:
        guard = f" if {self.context.text(case.guard)}" if case.guard else ""
        return shorten(
            self.context.language.case_label(case.pattern) + guard, LABEL_LIMIT
        )


def _arms(statement: m.If) -> list[tuple[m.Expr | None, Sequence[m.Stmt]]]:
    arms: list[tuple[m.Expr | None, Sequence[m.Stmt]]] = [
        (statement.test, statement.body)
    ]
    orelse = statement.orelse
    while len(orelse) == 1 and isinstance(orelse[0], m.If):
        arms.append((orelse[0].test, orelse[0].body))
        orelse = orelse[0].orelse
    if orelse:
        arms.append((None, orelse))
    return arms
