from typing import Any

from code_blueprints.analysis.metrics.class_cohesion import ClassCohesion
from code_blueprints.analysis.metrics.code_graph import (
    CodeGraph,
    FunctionGraph,
    QueryError,
)
from code_blueprints.analysis.metrics.coupling import Coupling
from code_blueprints.analysis.metrics.function_cohesion import FunctionCohesion
from code_blueprints.analysis.metrics.group_cohesion import GroupCohesion


class Cohesion:
    def __init__(
        self,
        code: CodeGraph,
        coupling: Coupling,
        function_graph: FunctionGraph | None,
    ) -> None:
        self._code = code
        self.classes = ClassCohesion(code)
        self.groups = GroupCohesion(code, coupling)
        self.functions = FunctionCohesion(function_graph)

    def cohesion(self, name: str) -> dict[str, Any]:
        node = self._code.resolve(name)
        if node.kind == "class":
            return self.classes.measure(node)
        if node.kind in ("module", "package"):
            return self.groups.measure(node)
        if node.kind in ("function", "method"):
            return self.functions.measure(node)
        raise QueryError(
            f"Cohesion is measured for packages, modules, classes and functions, not a {node.kind}."
        )
