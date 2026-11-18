from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from code_blueprints.analysis.model import Assign, ModuleCode, Node, Pattern

Locate = Callable[[str, str], str | None]


@dataclass(frozen=True)
class ImportBinding:
    absolute: str
    is_module: bool


@dataclass(frozen=True)
class Lowered:
    code: ModuleCode
    imports: dict[str, ImportBinding]


@dataclass(frozen=True)
class Syntax:
    operators: Mapping[str, tuple[str, int]]
    comparisons: Mapping[str, str]
    compare_precedence: int
    unary_prefixes: Mapping[str, str]
    unary_precedence: Mapping[str, int]
    keyword_separator: str
    conditional_first: bool
    unchained_operators: frozenset[str] = frozenset()
    brackets: Mapping[str, tuple[str, str]] = field(
        default_factory=lambda: {"list": ("[", "]"), "set": ("{", "}")}
    )


@dataclass(frozen=True)
class TypeNames:
    scalars: Mapping[str, str]
    lists: frozenset[str]
    maps: frozenset[str]
    transparent: frozenset[str]
    enum_bases: frozenset[str]
    struct_bases: frozenset[str]
    struct_decorators: frozenset[str]
    interface_bases: frozenset[str]
    model_bases: frozenset[str]
    optional: frozenset[str]
    union: frozenset[str]
    literal: frozenset[str]
    callables: frozenset[str]
    class_types: frozenset[str]
    awaitables: frozenset[str]
    guards: frozenset[str]
    tuples: frozenset[str]
    class_variable: frozenset[str]
    sequences: frozenset[str]
    mappings: frozenset[str]


@dataclass(frozen=True)
class Profile:
    builtin_names: frozenset[str]
    builtin_classes: frozenset[str]
    pure_builtins: frozenset[str]
    pure_methods: frozenset[str]
    pure_externals: frozenset[str]
    pure_external_modules: frozenset[str]
    builtin_parameters: Mapping[str, tuple[str, ...]]
    builtin_results: Mapping[str, tuple[str, str]]
    method_results: Mapping[str, tuple[str, str]]
    same_type_methods: frozenset[str]
    numeric_modules: frozenset[str]
    stdlib_modules: frozenset[str]
    none_text: str
    receiver_names: frozenset[str]
    instance_receiver: str
    constructor_name: str
    comprehensions: Mapping[str, tuple[str, str, str]]
    types: TypeNames
    super_name: str = "super"
    default_exception: str = "Exception"
    sequence_kinds: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    mapping_kind: tuple[str, str] = ("dict", "map")
    function_title: str = "Lambda"
    descriptor_method: str | None = None
    variadic_label: str = "{}"
    keywords_label: str = "{}"
    callable_label: str = "Callable"
    class_label: str = "type"
    handler_word: str = "except"
    match_title: str = "Match"
    spread_prefix: str = "*"
    mapping_spread_prefix: str = "**"
    follows_star_imports: bool = False
    optional_label: str = "Optional[{}]"
    literal_labels: Mapping[str, str] = field(default_factory=dict)


class Language:
    name: str = ""
    extensions: tuple[str, ...] = ()
    comment_prefix: str = "#"
    reads_other_files: bool = False
    profile: Profile
    syntax: Syntax

    def handles(self, path: str) -> bool:
        return path.endswith(self.extensions)

    def includes(self, path: str) -> bool:
        return True

    def module_name(self, path: str) -> str:
        raise NotImplementedError

    def is_package_init(self, path: str) -> bool:
        raise NotImplementedError

    def lower(self, path: str, name: str, source: str, locate: Locate) -> Lowered:
        raise NotImplementedError

    def text(self, node: Node) -> str:
        raise NotImplementedError

    def text_with(self, node: Node, replacements: Mapping[Node, str]) -> str:
        raise NotImplementedError

    def literal_text(self, value: object) -> str:
        raise NotImplementedError

    def is_constant(self, statement: Assign) -> bool:
        raise NotImplementedError

    def case_label(self, pattern: Pattern) -> str:
        return f"case {self.text(pattern)}"

    def parse_errors(self) -> tuple[type[Exception], ...]:
        return (SyntaxError, ValueError, RecursionError)


def stem_parts(path: str, extensions: tuple[str, ...]) -> list[str]:
    for extension in sorted(extensions, key=len, reverse=True):
        if path.endswith(extension):
            path = path[: -len(extension)]
            break
    return [part for part in PurePosixPath(path).parts if part]
