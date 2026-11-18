from dataclasses import replace
from code_blueprints.analysis.types import (
    UNKNOWN,
)
from code_blueprints.analysis import model as m
from code_blueprints.analysis.blueprint.text import (
    shorten,
    pin_name,
)
from code_blueprints.analysis.blueprint.values import BOOL, Value
from code_blueprints.analysis.blueprint.code_shapes import assigned_names
from code_blueprints.analysis.blueprint.code_shapes import flat_targets
from code_blueprints.analysis.blueprint.text import LABEL_LIMIT
from code_blueprints.analysis.blueprint.statements.context import BuildContext


class Bindings:
    def __init__(self, context: BuildContext) -> None:
        self.context = context

    def expression_statement(self, value: m.Expr) -> None:
        if isinstance(value, m.Literal):
            return
        if isinstance(value, m.Call):
            self.context.calls.call(value, exec_candidate=True, out_names=())
        elif isinstance(value, m.Await) and isinstance(value.value, m.Call):
            self.context.calls.call(
                value.value, exec_candidate=True, out_names=(), awaited=True
            )
        elif isinstance(value, m.Yield):
            self.context.expressions.yield_value(value, discard=True)
        else:
            self.context.expressions.value(value)

    def assign(self, statement: m.Assign, *, exec_candidate: bool) -> None:
        if statement.value is None:
            return
        targets = statement.targets
        names = assigned_names(targets[0]) if len(targets) == 1 else None
        call, awaited = _unwrap_call(statement.value)
        if (
            call is not None
            and names is not None
            and len(names) > 1
            and isinstance(targets[0], m.Sequence)
        ):
            outputs = self.context.calls.call(
                call, exec_candidate=exec_candidate, out_names=names, awaited=awaited
            )
            for target, output in zip(flat_targets(targets[0]), outputs):
                self.bind(target, output, statement.line)
            return
        out_name = names[0] if names is not None and len(names) == 1 else ""
        value = self.context.expressions.value(
            statement.value, exec_candidate=exec_candidate, out_name=out_name
        )
        if statement.annotation is not None:
            value = replace(
                value,
                type=self.context.lookups.annotation(statement.annotation),
                annotation=(statement.annotation, self.context.module),
            )
        for target in targets:
            self.bind(target, value, statement.line)

    def bind(self, target: m.Expr, value: Value, line: int) -> None:
        if isinstance(target, m.Name):
            self._bind_name(target.id, value, line)
        elif isinstance(target, m.Spread):
            self.bind(target.value, value, line)
        elif isinstance(target, m.Sequence):
            for element, part in zip(
                target.elements, self._unpack(value, target, line)
            ):
                self.bind(element, part, line)
        elif isinstance(target, m.Member):
            node = self.context.graph.add(
                "set", f"Set {self.context.text(target)}", line
            )
            self.context.graph.connect(
                node,
                pin_name(target.value),
                self.context.expressions.value(target.value),
            )
            self.context.graph.connect(node, "value", value)
            self.context.flow.step(node)
        elif isinstance(target, m.Subscript):
            container = self.context.expressions.value(target.value)
            key = self.context.expressions.value(target.index)
            node = self.context.graph.add(
                "set", f"Set {self.context.text(target)}", line
            )
            self.context.graph.connect(node, pin_name(target.value), container)
            self.context.graph.connect(node, "key", key)
            self.context.graph.connect(node, "value", value)
            self.context.flow.step(node)

    def _bind_name(self, name: str, value: Value, line: int) -> None:
        if name in self.context.carried or name in self.context.scope.declared_globals:
            node = self.context.graph.add("set", f"Set {name}", line)
            self.context.graph.connect(node, "value", value)
            self.context.flow.step(node)
            value = self.context.graph.output(node, name, value.type, value.annotation)
        self.context.scope.bind(name, value)

    def _unpack(self, value: Value, target: m.Sequence, line: int) -> list[Value]:
        node = self.context.graph.add("op", "Unpack", line)
        self.context.graph.connect(node, "value", value)
        return [
            self.context.graph.output(node, self.target_label(element), UNKNOWN)
            for element in target.elements
        ]

    def augmented_assign(self, statement: m.AugAssign) -> None:
        symbol = statement.op
        target = statement.target
        value = self.context.expressions.value(statement.value)
        if isinstance(target, m.Name):
            current = self.context.scope.value_of(target.id, statement.line)
            node = self.context.graph.add(
                "set", f"Set {target.id} {symbol}=", statement.line
            )
            self.context.graph.connect(node, target.id, current)
            self.context.graph.connect(node, "value", value)
            self.context.flow.step(node)
            self.context.scope.bind(
                target.id,
                self.context.graph.output(
                    node, target.id, current.type, current.annotation
                ),
            )
            return
        base = target.value if isinstance(target, (m.Member, m.Subscript)) else target
        container = self.context.expressions.value(base)
        key = (
            self.context.expressions.value(target.index)
            if isinstance(target, m.Subscript)
            else None
        )
        node = self.context.graph.add(
            "set", f"Set {self.context.text(target)} {symbol}=", statement.line
        )
        self.context.graph.connect(node, pin_name(base), container)
        if key is not None:
            self.context.graph.connect(node, "key", key)
        self.context.graph.connect(node, "value", value)
        self.context.flow.step(node)

    def delete(self, statement: m.Delete) -> None:
        for target in statement.targets:
            if isinstance(target, m.Name):
                self.context.scope.forget(target.id)
                continue
            base = (
                target.value if isinstance(target, (m.Member, m.Subscript)) else target
            )
            container = self.context.expressions.value(base)
            key = (
                self.context.expressions.value(target.index)
                if isinstance(target, m.Subscript)
                else None
            )
            node = self.context.graph.add(
                "set", f"Delete {self.context.text(target)}", statement.line
            )
            self.context.graph.connect(node, pin_name(base), container)
            if key is not None:
                self.context.graph.connect(node, "key", key)
            self.context.flow.step(node)

    def assert_statement(self, statement: m.Assert) -> None:
        condition = self.context.expressions.value(statement.test)
        node = self.context.graph.add("raise", "Assert", statement.line)
        self.context.graph.connect(node, "condition", condition, BOOL)
        if statement.msg is not None:
            self.context.graph.connect(
                node, "message", self.context.expressions.value(statement.msg)
            )
        self.context.flow.step(node)

    def return_statement(self, statement: m.Return) -> None:
        value = (
            self.context.expressions.value(statement.value, exec_candidate=True)
            if statement.value is not None
            else None
        )
        self.emit_return(value, statement.line)

    def emit_return(self, value: Value | None, line: int) -> None:
        node = self.context.graph.add("return", "Return", line)
        if value is not None:
            declared = self.context.return_type
            name = declared.label if declared is not None else "value"
            self.context.graph.connect(
                node,
                name,
                value,
                (
                    declared
                    if declared is not None and declared.cat != "any"
                    else value.type
                ),
            )
        self.context.flow.step(node)
        self.context.flow.resume([])

    def target_label(self, target: m.Expr) -> str:
        if isinstance(target, m.Name):
            return target.id
        if isinstance(target, m.Spread):
            return (
                f"{self.context.profile.spread_prefix}{self.target_label(target.value)}"
            )
        return shorten(self.context.text(target), LABEL_LIMIT)


def _unwrap_call(value: m.Expr) -> tuple[m.Call | None, bool]:
    if isinstance(value, m.Call):
        return value, False
    if isinstance(value, m.Await) and isinstance(value.value, m.Call):
        return value.value, True
    return None, False
