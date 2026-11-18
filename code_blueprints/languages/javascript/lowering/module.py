from tree_sitter import Node as Syntax

from code_blueprints.analysis import model as m
from code_blueprints.languages.javascript import nodes as ts
from code_blueprints.languages.javascript.annotations import TypeAnnotations
from code_blueprints.languages.javascript.links import ModuleLinks
from code_blueprints.languages.language import Language, Locate
from code_blueprints.languages.javascript.lowering.bindings import Bindings
from code_blueprints.languages.javascript.lowering.classes import Classes
from code_blueprints.languages.javascript.lowering.composites import Composites
from code_blueprints.languages.javascript.lowering.control import ControlFlow
from code_blueprints.languages.javascript.lowering.exports import Exports
from code_blueprints.languages.javascript.lowering.expressions import Expressions
from code_blueprints.languages.javascript.lowering.functions import Functions
from code_blueprints.languages.javascript.lowering.jsx import Jsx
from code_blueprints.languages.javascript.lowering.operators import Operators
from code_blueprints.languages.javascript.lowering.state import LoweringState
from code_blueprints.languages.javascript.lowering.statements import Statements
from code_blueprints.languages.javascript.lowering.targets import Targets


class Lowering:
    def __init__(
        self, language: Language, path: str, name: str, locate: Locate
    ) -> None:
        self.state = LoweringState(language, ModuleLinks(path, name, locate))
        self.links = self.state.links
        self.statements = Statements(self.state)
        self.control = ControlFlow()
        self.exports = Exports(self.state)
        self.bindings = Bindings(self.state)
        self.functions = Functions(self.state)
        self.classes = Classes(self.state)
        self.expressions = Expressions(self.state)
        self.operators = Operators()
        self.targets = Targets()
        self.composites = Composites(self.state)
        self.jsx = Jsx(self.state)
        self.types = TypeAnnotations(self.expressions.expr)
        self._wire_statements()
        self._wire_definitions()
        self._wire_expressions()

    def module(self, root: Syntax) -> list[m.Stmt]:
        return self.statements.block(ts.named(root))

    def _wire_statements(self) -> None:
        self.statements.bindings = self.bindings
        self.statements.classes = self.classes
        self.statements.control = self.control
        self.statements.exports = self.exports
        self.statements.expressions = self.expressions
        self.statements.functions = self.functions
        self.control.bindings = self.bindings
        self.control.expressions = self.expressions
        self.control.statements = self.statements
        self.control.targets = self.targets
        self.exports.classes = self.classes
        self.exports.expressions = self.expressions
        self.exports.functions = self.functions
        self.exports.statements = self.statements
        self.bindings.classes = self.classes
        self.bindings.expressions = self.expressions
        self.bindings.functions = self.functions
        self.bindings.statements = self.statements
        self.bindings.targets = self.targets
        self.bindings.types = self.types

    def _wire_definitions(self) -> None:
        self.functions.expressions = self.expressions
        self.functions.statements = self.statements
        self.functions.targets = self.targets
        self.functions.types = self.types
        self.classes.expressions = self.expressions
        self.classes.functions = self.functions
        self.classes.types = self.types

    def _wire_expressions(self) -> None:
        self.expressions.classes = self.classes
        self.expressions.composites = self.composites
        self.expressions.functions = self.functions
        self.expressions.jsx = self.jsx
        self.expressions.operators = self.operators
        self.operators.expressions = self.expressions
        self.operators.targets = self.targets
        self.targets.expressions = self.expressions
        self.composites.expressions = self.expressions
        self.composites.functions = self.functions
        self.jsx.expressions = self.expressions
