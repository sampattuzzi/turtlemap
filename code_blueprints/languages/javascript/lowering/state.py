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
