from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from turtlemap.analysis import model as m
from turtlemap.languages.language import ImportBinding, Language, Locate
from turtlemap.languages.registry import STDLIB_MODULES, language_for


@dataclass(frozen=True)
class SymbolRef:
    path: str
    sym: str

    def to_json(self) -> dict[str, str]:
        return {"path": self.path, "sym": self.sym}


@dataclass(frozen=True)
class ModuleRef:
    path: str


@dataclass(frozen=True)
class ExternalRef:
    module: str
    name: str | None


Resolved = SymbolRef | ModuleRef | ExternalRef


@dataclass(frozen=True)
class ParsedFunction:
    qualname: str
    node: m.FunctionDecl
    class_qualname: str | None


@dataclass(frozen=True)
class ParsedClass:
    qualname: str
    node: m.ClassDecl
    methods: dict[str, str]


@dataclass
class ParsedModule:
    path: str
    name: str
    source: str
    lines: list[str]
    code: m.ModuleCode
    language: Language
    imports: dict[str, ImportBinding] = field(default_factory=dict)
    import_statements: list[m.Import] = field(default_factory=list)
    star_imports: list[str] = field(default_factory=list)
    classes: dict[str, ParsedClass] = field(default_factory=dict)
    functions: dict[str, ParsedFunction] = field(default_factory=dict)
    top_level: dict[str, str] = field(default_factory=dict)

    @property
    def body(self) -> list[m.Stmt]:
        return self.code.body

    @property
    def package(self) -> str:
        if self.language.is_package_init(self.path):
            return self.name
        return self.name.rpartition(".")[0]


@dataclass(frozen=True)
class ParseFailure:
    path: str
    message: str


def module_name_for(path: str) -> str:
    language = language_for(path)
    if language is None:
        return ".".join(part for part in PurePosixPath(path).parts if part)
    return language.module_name(path)


def library_of(module: str) -> str:
    top = module.split(".")[0]
    return "stdlib" if top in STDLIB_MODULES else top


def parse_module(
    path: str, absolute: Path, locate: Locate
) -> ParsedModule | ParseFailure:
    language = language_for(path)
    if language is None:
        return ParseFailure(path, "Not a supported language")
    errors: tuple[type[Exception], ...] = (
        OSError,
        UnicodeDecodeError,
        *language.parse_errors(),
    )
    try:
        source = absolute.read_text(encoding="utf-8")
        name = module_name_for(path)
        lowered = language.lower(path, name, source, locate)
    except errors as error:
        return ParseFailure(path, f"{type(error).__name__}: {error}")
    module = ParsedModule(
        path=path,
        name=name,
        source=source,
        lines=source.splitlines(),
        code=lowered.code,
        language=language,
    )
    _collect_imports(module, lowered.imports)
    _collect_definitions(module, module.body, prefix="", class_qualname=None)
    return module


def _collect_imports(module: ParsedModule, extra: dict[str, ImportBinding]) -> None:
    pending: deque[m.Node] = deque(module.body)
    while pending:
        node = pending.popleft()
        pending.extend(
            child
            for child in m.children(node)
            if not isinstance(child, (m.Expr, m.TypeExpr))
        )
        if not isinstance(node, m.Import):
            continue
        if node.whole:
            module.import_statements.append(node)
            for alias in node.names:
                if alias.alias:
                    module.imports[alias.alias] = ImportBinding(alias.name, True)
                else:
                    head = alias.name.partition(".")[0]
                    module.imports.setdefault(head, ImportBinding(head, True))
            continue
        base = node.module
        if base is None:
            continue
        module.import_statements.append(node)
        for alias in node.names:
            if alias.name == "*":
                if module.language.profile.follows_star_imports:
                    module.star_imports.append(base)
                continue
            module.imports[alias.alias or alias.name] = ImportBinding(
                f"{base}.{alias.name}" if base else alias.name, False
            )
    module.imports.update(extra)


def _collect_definitions(
    module: ParsedModule,
    body: Sequence[m.Stmt],
    *,
    prefix: str,
    class_qualname: str | None,
) -> None:
    for statement in body:
        if isinstance(statement, m.FunctionDef):
            function = statement.function
            qualname = prefix + function.name
            existing = module.functions.get(qualname)
            if existing is None or existing.node.is_overload:
                module.functions[qualname] = ParsedFunction(
                    qualname, function, class_qualname
                )
            if class_qualname is not None:
                module.classes[class_qualname].methods.setdefault(
                    function.name, qualname
                )
            elif not prefix:
                module.top_level[function.name] = qualname
        elif isinstance(statement, m.ClassDef):
            qualname = prefix + statement.cls.name
            module.classes[qualname] = ParsedClass(qualname, statement.cls, {})
            if not prefix:
                module.top_level[statement.cls.name] = qualname
            _collect_definitions(
                module,
                statement.cls.body,
                prefix=qualname + ".",
                class_qualname=qualname,
            )
        elif (
            isinstance(statement, (m.If, m.Try))
            and class_qualname is None
            and not prefix
        ):
            nested: list[m.Stmt] = list(statement.body)
            if isinstance(statement, m.If):
                nested += statement.orelse
            else:
                nested += list(statement.orelse) + list(statement.finalbody)
                for handler in statement.handlers:
                    nested += handler.body
            _collect_definitions(module, nested, prefix=prefix, class_qualname=None)
