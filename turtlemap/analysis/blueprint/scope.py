from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import replace

from turtlemap.analysis.blueprint.callees import external_name
from turtlemap.analysis.blueprint.syntax import Form
from turtlemap.analysis.blueprint.canvas import Graph, GraphNode, Pin
from turtlemap.analysis.blueprint.lookups import TypeLookups
from turtlemap.analysis.blueprint.values import (
    BOOL,
    CALLABLE,
    Environment,
    Value,
    select_type,
)
from turtlemap.analysis.types import UNKNOWN, PinType
from turtlemap.analysis.workspace.parsed import ExternalRef, ModuleRef, SymbolRef


class Scope:
    def __init__(
        self,
        lookups: TypeLookups,
        graph: Graph,
        local_names: frozenset[str],
        *,
        parent: "Scope | None" = None,
        frame: str | None = None,
        variables: frozenset[str] = frozenset(),
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
        self._variable_names = variables
        self._declared: dict[str, tuple[Value, str | None]] = {}
        self._reads: dict[tuple[str, str | None, int], Value] = {}
        self._globals: dict[str, Value] = {}

    def restore(self, env: Environment) -> None:
        self.env = env

    def bind(self, name: str, value: Value) -> None:
        self.env[name] = value

    @contextmanager
    def local_bindings(self, names: Iterable[str]) -> Iterator[None]:
        saved = dict(self.env)
        hidden = {
            name: self._declared.pop(name) for name in names if name in self._declared
        }
        try:
            yield
        finally:
            self.env = saved
            self._declared.update(hidden)

    def forget(self, name: str) -> None:
        self.env.pop(name, None)

    def declare_globals(self, names: list[str]) -> None:
        self.declared_globals.update(names)

    def define_function(self, name: str) -> None:
        self.local_functions.add(name)

    def value_of(self, name: str, line: int) -> Value:
        declared = self.declared(name)
        if declared is not None:
            return self.read(declared, name, line)
        if name in self.env:
            return self.env[name]
        reference = self.reference(name, line)
        if reference is not None:
            return self.read(reference, name, line)
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
        if self._owns(name) or self.is_variable(name):
            return True
        return self.parent is not None and self.parent.is_local(name)

    def is_variable(self, name: str) -> bool:
        if name in self._variable_names:
            return True
        if self._owns(name):
            return False
        if self.parent is not None:
            return self.parent.is_variable(name)
        return name in self._lookups.reassigned_globals

    def owns_variable(self, name: str) -> bool:
        return name in self._variable_names

    def declared(self, name: str) -> Value | None:
        found = self._declared.get(name)
        if found is None:
            return None
        value, frame = found
        return value if self._graph.encloses(frame, self._graph.frame) else None

    def declare(self, name: str, reference: Value) -> None:
        self._declared[name] = (reference, self._graph.frame)
        self.env.pop(name, None)

    def known_reference(self, name: str, line: int) -> Value | None:
        if name in self._variable_names:
            return self.declared(name)
        return self.reference(name, line)

    def reference(self, name: str, line: int) -> Value | None:
        if not self.is_variable(name):
            return None
        if name in self._variable_names:
            return self.declared(name) or self._undeclared(name, line)
        if self.parent is not None:
            return self.parent.reference(name, line)
        return self._cached_variable(
            f"cell:{name}",
            line,
            lambda: self._graph.add("var", name, line),
            self._lookups.module_variable(name),
            cell=True,
        )

    def settle(self, name: str, pin_type: PinType) -> None:
        found = self._declared.get(name)
        if found is None or found[0].node is None or found[0].pin is None:
            if self.parent is not None and not self._owns(name):
                self.parent.settle(name, pin_type)
            return
        reference, frame = found
        if reference.type.cat != "any" or pin_type.cat in ("any", "none"):
            return
        assert reference.node is not None and reference.pin is not None
        node = self._graph.node(reference.node)
        for pin in [node.output(reference.pin), _input(node, "value")]:
            if pin is not None and pin.type.cat == "any":
                pin.type = pin_type
        self._declared[name] = (replace(reference, type=pin_type), frame)

    def read(self, reference: Value, name: str, line: int) -> Value:
        key = (name, self._graph.frame, self._graph.moment)
        cached = self._reads.get(key)
        if cached is not None:
            return cached
        node = self._graph.add("get", "Get", line)
        node.form = Form("value")
        self._graph.connect(node, name, reference)
        value = self._graph.output(node, name, reference.type)
        self._reads[key] = value
        return value

    def _undeclared(self, name: str, line: int) -> Value:
        with self._graph.inside(self.frame):
            node = self._graph.add("var", name, line, note="set later")
            node.form = Form("store")
            reference = self._graph.output(node, name, UNKNOWN, cell=True)
            self.declare(name, reference)
        return reference

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

    def select(
        self, condition: Value, when_true: Value, when_false: Value, line: int
    ) -> Value:
        if when_true == when_false:
            return when_true
        result = select_type(when_true, when_false)
        node = self._graph.add("select", "Select", line)
        node.form = Form("select")
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
        node.form = Form("value")
        value = self._graph.output(
            node, key.removeprefix("cell:").rsplit(".", 1)[-1], pin_type, cell=cell
        )
        self._globals[key] = value
        return value


def _input(node: GraphNode, name: str) -> Pin | None:
    return next((pin for pin in node.ins if pin.name == name), None)
