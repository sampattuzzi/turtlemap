from code_blueprints.analysis.types import (
    TypeSystem,
)
from code_blueprints.analysis import model as m
from code_blueprints.analysis.workspace.parsed import (
    ParsedFunction,
    ParsedModule,
    SymbolRef,
)
from code_blueprints.languages.language import Language, Profile
from code_blueprints.analysis.blueprint.canvas import (
    Flow,
    MAX_NODES,
    Graph,
    Tail,
)
from code_blueprints.analysis.blueprint.callees import Callees
from code_blueprints.analysis.blueprint.evaluation.expressions import Expressions
from code_blueprints.analysis.blueprint.lookups import TypeLookups
from code_blueprints.analysis.blueprint.scope import Scope


class BuildContext:
    def __init__(
        self, types: TypeSystem, module: ParsedModule, function: ParsedFunction
    ) -> None:
        self.types = types
        self.module = module
        self.language: Language = module.language
        self.profile: Profile = module.language.profile
        self.function = function
        self.graph = Graph(MAX_NODES)
        self.lookups = TypeLookups(types, module)
        self.scope = Scope(self.lookups, self.graph, m.bound_names(function.node))
        self.flow = Flow(self.graph)
        self.expressions = Expressions(
            self.lookups,
            Callees(self.lookups),
            self.scope,
            self.flow,
            self.owner_ref(),
            function.node,
        )
        self.calls = self.expressions.calls
        self.carried: frozenset[str] = frozenset()
        self.loop_exits: list[list[Tail]] = []
        self.parameter_annotations = {
            parameter.name: parameter.annotation
            for parameter in function.node.params
            if parameter.annotation is not None
        }
        self.return_type = (
            self.lookups.resolver(module).annotation(function.node.returns)
            if function.node.returns is not None
            else None
        )

    def text(self, node: m.Node) -> str:
        return self.language.text(node)

    def owner_ref(self) -> SymbolRef | None:
        qualname = self.function.class_qualname
        return SymbolRef(self.module.path, qualname) if qualname is not None else None
