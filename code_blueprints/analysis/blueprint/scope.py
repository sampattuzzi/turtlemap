from collections.abc import Callable

from dataclasses import replace

from code_blueprints.analysis.blueprint.callees import external_name
from code_blueprints.analysis.blueprint.canvas import Graph, GraphNode
from code_blueprints.analysis.blueprint.lookups import TypeLookups
from code_blueprints.analysis.blueprint.values import (
    BOOL,
    CALLABLE,
    Binding,
    Environment,
    PendingSelect,
    Value,
    select_type,
)
from code_blueprints.analysis.types import UNKNOWN, PinType
from code_blueprints.analysis.workspace.parsed import ExternalRef, ModuleRef, SymbolRef


class Scope:
    def __init__(
        self,
        lookups: TypeLookups,
        graph: Graph,
        local_names: frozenset[str],
        *,
        parent: "Scope | None" = None,
        frame: str | None = None,
        cells: frozenset[str] = frozenset(),
    ) -> None:
        self._lookups = lookups
        self._workspace = lookups.workspace
        self._module = lookups.module
        self._profile = lookups.profile
        self._graph = graph
        self.parent = parent
        self.frame = frame
        self.env: Environment = {}
        self.local_names = local_names
        self.local_functions: set[str] = set()
        self.declared_globals: set[str] = set()
        self._cell_names = cells
        self._cells: dict[str, Value] = {}
        self._reads: dict[tuple[str, str | None, int], Value] = {}
        self._materialized: dict[PendingSelect, Value] = {}
        self._globals: dict[str, Value] = {}

    def restore(self, env: Environment) -> None:
        self.env = env

    def bind(self, name: str, value: Binding) -> None:
        self.env[name] = value

    def forget(self, name: str) -> None:
        self.env.pop(name, None)

    def declare_globals(self, names: list[str]) -> None:
        self.declared_globals.update(names)

    def define_function(self, name: str) -> None:
        self.local_functions.add(name)

    def value_of(self, name: str, line: int) -> Value:
        cell = self.cell(name, line)
        if cell is not None:
            return self.read(cell, name, line)
        if name in self.env:
            value = self.materialize(self.env[name])
            self.env[name] = value
            return value
        if name in self.local_functions:
            return Value(CALLABLE, literal=name)
        if self._owns(name):
            return self._cached_variable(
                name,
                line,
                lambda: self._graph.add(
                    "var", name, line, note="Assigned later in the function"
                ),
                UNKNOWN,
            )
        if self.parent is not None:
            with self._graph.inside(self.parent.frame):
                return self.parent.value_of(name, line)
        return self.global_value(name, line)

    def is_local(self, name: str) -> bool:
        if self._owns(name) or self.is_cell(name):
            return True
        return self.parent is not None and self.parent.is_local(name)

    def is_cell(self, name: str) -> bool:
        if name in self._cell_names:
            return True
        if self._owns(name):
            return False
        if self.parent is not None:
            return self.parent.is_cell(name)
        return name in self._lookups.reassigned_globals

    def cell(self, name: str, line: int) -> Value | None:
        if not self.is_cell(name):
            return None
        if name in self._cell_names:
            return self._own_cell(name, line)
        if self.parent is not None:
            return self.parent.cell(name, line)
        return self._cached_variable(
            f"cell:{name}",
            line,
            lambda: self._graph.add("var", name, line),
            self._lookups.module_variable(name),
            cell=True,
        )

    def settle(self, name: str, pin_type: PinType) -> None:
        cell = self._cells.get(name)
        if cell is None or cell.node is None or cell.pin is None:
            if self.parent is not None and not self._owns(name):
                self.parent.settle(name, pin_type)
            return
        if cell.type.cat != "any" or pin_type.cat in ("any", "none"):
            return
        pin = self._graph.node(cell.node).output(cell.pin)
        if pin is not None:
            pin.type = pin_type
        self._cells[name] = replace(cell, type=pin_type)

    def read(self, cell: Value, name: str, line: int) -> Value:
        key = (name, self._graph.frame, self._graph.moment)
        cached = self._reads.get(key)
        if cached is not None:
            return cached
        node = self._graph.add("get", "Get", line)
        self._graph.connect(node, name, cell, cell=True)
        value = self._graph.output(node, name, cell.type)
        self._reads[key] = value
        return value

    def _own_cell(self, name: str, line: int) -> Value:
        cached = self._cells.get(name)
        if cached is not None:
            return cached
        with self._graph.inside(self.frame):
            node = self._graph.add("var", name, line, note="captured local")
        value = self._graph.output(node, name, UNKNOWN, cell=True)
        self._cells[name] = value
        return value

    def _owns(self, name: str) -> bool:
        return (
            name in self.env
            or name in self.local_functions
            or (name in self.local_names and name not in self.declared_globals)
        )

    def global_value(self, dotted: str, line: int) -> Value:
        if self.parent is not None:
            with self._graph.inside(self.parent.frame):
                return self.parent.global_value(dotted, line)
        head = dotted.split(".")[0]
        if (
            head in self._profile.builtin_names
            and head not in self._module.imports
            and head not in self._module.top_level
            and head not in self._lookups.module_variables
        ):
            return Value(
                (
                    PinType(head, "class")
                    if head in self._profile.builtin_classes
                    else CALLABLE
                ),
                literal=dotted,
            )
        if head in self._lookups.module_variables and "." not in dotted:
            return self._cached_variable(
                dotted,
                line,
                lambda: self._graph.add("var", dotted, line),
                self._lookups.module_variable(head),
            )
        resolved = self._workspace.resolve(self._module, dotted)
        if isinstance(resolved, SymbolRef):
            return self._project_symbol_value(dotted, resolved, line)
        if isinstance(resolved, ExternalRef):
            external = external_name(resolved)
            last = dotted.rsplit(".", 1)[-1]
            if last[:1].isupper():
                return Value(
                    PinType(last, "class" if not last.isupper() else "any"),
                    literal=dotted,
                )
            return self._cached_variable(
                dotted,
                line,
                lambda: self._graph.add("var", dotted, line, external=external),
                UNKNOWN,
            )
        if isinstance(resolved, ModuleRef):
            return Value(UNKNOWN, literal=dotted)
        return self._cached_variable(
            dotted, line, lambda: self._graph.add("var", dotted, line), UNKNOWN
        )

    def materialize(self, binding: Binding) -> Value:
        if isinstance(binding, Value):
            return binding
        cached = self._materialized.get(binding)
        if cached is None:
            when_true = self.materialize(binding.when_true)
            when_false = self.materialize(binding.when_false)
            cached = self.select(binding.condition, when_true, when_false, binding.line)
            self._materialized[binding] = cached
        return cached

    def select(
        self, condition: Value, when_true: Value, when_false: Value, line: int
    ) -> Value:
        if when_true == when_false:
            return when_true
        result = select_type(when_true, when_false)
        node = self._graph.add("select", "Select", line)
        self._graph.connect(node, "condition", condition, BOOL)
        self._graph.connect(node, "if true", when_true)
        self._graph.connect(node, "if false", when_false)
        return self._graph.output(node, "", result)

    def _project_symbol_value(self, dotted: str, ref: SymbolRef, line: int) -> Value:
        if self._workspace.parsed_class(ref) is not None:
            class_type = self._lookups.system.class_type(ref)
            if dotted.rsplit(".", 1)[-1] == ref.sym.rsplit(".", 1)[-1]:
                return Value(replace(class_type, cat="class"), literal=dotted)
            return Value(
                class_type if class_type.cat == "enum" else UNKNOWN, literal=dotted
            )
        return self._cached_variable(
            dotted,
            line,
            lambda: self._graph.add("var", dotted, line, target=ref),
            CALLABLE,
        )

    def _cached_variable(
        self,
        key: str,
        line: int,
        create: Callable[[], GraphNode],
        pin_type: PinType,
        *,
        cell: bool = False,
    ) -> Value:
        cached = self._globals.get(key)
        if cached is not None:
            return cached
        with self._graph.inside(self.frame):
            node = create()
        value = self._graph.output(
            node, key.removeprefix("cell:").rsplit(".", 1)[-1], pin_type, cell=cell
        )
        self._globals[key] = value
        return value


def merge(
    condition: Value,
    true_env: Environment,
    false_env: Environment,
    line: int,
) -> Environment:
    merged: Environment = {}
    for name in [*true_env, *(name for name in false_env if name not in true_env)]:
        when_true, when_false = true_env.get(name), false_env.get(name)
        if when_true is None or when_false is None or when_true == when_false:
            present = when_true if when_true is not None else when_false
            if present is not None:
                merged[name] = present
            continue
        merged[name] = PendingSelect(condition, when_true, when_false, line)
    return merged
