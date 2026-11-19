from turtlemap.analysis.types import (
    TypeSystem,
)
from turtlemap.analysis import model as m
from turtlemap.analysis.workspace.parsed import (
    ParsedFunction,
    ParsedModule,
    SymbolRef,
)
from turtlemap.languages.language import Language, Profile
from turtlemap.analysis.blueprint.canvas import (
    Flow,
    MAX_NODES,
    Graph,
    GraphNode,
    Tail,
)
from turtlemap.analysis.blueprint.captures import shared_and_changing
from turtlemap.analysis.blueprint.callees import Callees
from turtlemap.analysis.blueprint.evaluation.expressions import Expressions
from turtlemap.analysis.blueprint.lookups import TypeLookups
from turtlemap.analysis.blueprint.scope import Scope


class BuildContext:
    def __init__(
        self,
        types: TypeSystem,
        module: ParsedModule,
        function: ParsedFunction,
        *,
        parent: "BuildContext | None" = None,
        frame: GraphNode | None = None,
    ) -> None:
        self.types = types
        self.module = module
        self.language: Language = module.language
        self.profile: Profile = module.language.profile
        self.function = function
        self.frame = frame
        self.graph: Graph = parent.graph if parent is not None else Graph(MAX_NODES)
        self.lookups: TypeLookups = (
            parent.lookups if parent is not None else TypeLookups(types, module)
        )
        self.scope: Scope = Scope(
            self.lookups,
            self.graph,
            m.bound_names(function.node),
            parent=parent.scope if parent is not None else None,
            frame=frame.id if frame is not None else None,
            cells=shared_and_changing(function.node),
        )
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

    def nested(self, function: m.FunctionDecl, frame: GraphNode) -> "BuildContext":
        return BuildContext(
            self.types,
            self.module,
            ParsedFunction(
                f"{self.function.qualname}.{function.name}",
                function,
                self.function.class_qualname,
            ),
            parent=self,
            frame=frame,
        )

    def text(self, node: m.Node) -> str:
        return self.language.text(node)

    def owner_ref(self) -> SymbolRef | None:
        qualname = self.function.class_qualname
        return SymbolRef(self.module.path, qualname) if qualname is not None else None
