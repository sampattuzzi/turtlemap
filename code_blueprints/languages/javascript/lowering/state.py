from code_blueprints.analysis import model as m
from code_blueprints.languages.javascript.links import ModuleLinks
from code_blueprints.languages.language import Language


class LoweringState:
    def __init__(self, language: Language, links: ModuleLinks) -> None:
        self.language = language
        self.links = links
        self.hoisted: list[m.Stmt] = []
        self.scopes: list[set[str]] = [set()]
        self.receivers: list[str | None] = [None]
        self.declared: list[set[str]] = [set()]

    def declare(self, target: m.Node) -> None:
        self.declared[-1].update(
            node.id
            for node in m.walk(target)
            if isinstance(node, m.Name) and node.store
        )

    def declare_name(self, name: str) -> None:
        self.declared[-1].add(name)

    def enter_function(self) -> None:
        self.declared.append(set())

    def leave_function(
        self, params: list[m.Parameter], body: list[m.Stmt]
    ) -> list[m.Stmt]:
        declared = self.declared.pop() | {parameter.name for parameter in params}
        line = body[0].line if body else 0
        probe = m.Function(line, line, params, body)
        outer = sorted(m.bound_names(probe) - declared)
        if not outer:
            return body
        return [m.Global(line, line, outer), *body]
