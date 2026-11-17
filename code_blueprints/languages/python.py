import ast
import builtins
import copy
import sys
import warnings
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from code_blueprints.analysis import model as m
from code_blueprints.languages.language import (
    ImportBinding,
    Language,
    Locate,
    Lowered,
    Profile,
    Syntax,
    TypeNames,
    stem_parts,
)

_LIST_TYPES = frozenset(
    {
        "list",
        "List",
        "Sequence",
        "MutableSequence",
        "Iterable",
        "Iterator",
        "Collection",
        "Generator",
        "AsyncIterator",
        "AsyncIterable",
        "AsyncGenerator",
        "deque",
        "Deque",
        "tuple",
        "Tuple",
        "set",
        "Set",
        "frozenset",
        "FrozenSet",
        "AbstractSet",
        "MutableSet",
        "KeysView",
        "ValuesView",
        "NDArray",
        "ndarray",
    }
)
_MAP_TYPES = frozenset(
    {
        "dict",
        "Dict",
        "Mapping",
        "MutableMapping",
        "FrozenDict",
        "defaultdict",
        "DefaultDict",
        "OrderedDict",
        "Counter",
        "ChainMap",
    }
)
_SEQUENCE_ANNOTATIONS = frozenset(
    {
        "list",
        "List",
        "Sequence",
        "MutableSequence",
        "Iterable",
        "Iterator",
        "Collection",
        "set",
        "Set",
        "frozenset",
        "FrozenSet",
        "AbstractSet",
        "deque",
        "Deque",
        "Generator",
        "AsyncIterator",
        "AsyncIterable",
        "AsyncGenerator",
        "KeysView",
        "ValuesView",
    }
)
_MAPPING_ANNOTATIONS = frozenset(
    {
        "dict",
        "Dict",
        "Mapping",
        "MutableMapping",
        "FrozenDict",
        "defaultdict",
        "DefaultDict",
        "OrderedDict",
    }
)

PYTHON_TYPES = TypeNames(
    scalars={
        "bool": "bool",
        "int": "int",
        "float": "float",
        "complex": "float",
        "Decimal": "float",
        "float64": "float",
        "float32": "float",
        "int64": "int",
        "int32": "int",
        "str": "str",
        "bytes": "bytes",
        "bytearray": "bytes",
        "memoryview": "bytes",
        "None": "none",
        "NoneType": "none",
        "datetime": "time",
        "date": "time",
        "time": "time",
        "timedelta": "time",
        "Timestamp": "time",
        "Timedelta": "time",
        "tzinfo": "time",
        "ZoneInfo": "time",
        "Any": "any",
        "object": "any",
        "Path": "str",
        "PurePath": "str",
        "PurePosixPath": "str",
        "UUID": "str",
    },
    lists=_LIST_TYPES,
    maps=_MAP_TYPES,
    transparent=frozenset(
        {
            "Annotated",
            "Final",
            "ClassVar",
            "Required",
            "NotRequired",
            "ReadOnly",
            "Awaitable",
            "InitVar",
        }
    ),
    enum_bases=frozenset({"Enum", "StrEnum", "IntEnum", "Flag", "IntFlag"}),
    struct_bases=frozenset(
        {"BaseModel", "NamedTuple", "TypedDict", "Struct", "BaseSettings", "RootModel"}
    ),
    struct_decorators=frozenset(
        {"dataclass", "attrs", "define", "frozen", "s", "dataclass_json"}
    ),
    interface_bases=frozenset({"Protocol", "ABC"}),
    model_bases=frozenset({"BaseModel", "BaseSettings", "RootModel"}),
    optional=frozenset({"Optional"}),
    union=frozenset({"Union"}),
    literal=frozenset({"Literal"}),
    callables=frozenset({"Callable", "Coroutine"}),
    class_types=frozenset({"type", "Type"}),
    awaitables=frozenset({"Coroutine"}),
    guards=frozenset({"TypeGuard", "TypeIs"}),
    tuples=frozenset({"tuple", "Tuple"}),
    class_variable=frozenset({"ClassVar"}),
    sequences=_SEQUENCE_ANNOTATIONS,
    mappings=_MAPPING_ANNOTATIONS,
)

_STR = ("str", "str")
_BOOL = ("bool", "bool")
_INT = ("int", "int")
_FLOAT = ("float", "float")
_LIST = ("list", "list")
_BYTES = ("bytes", "bytes")
_DICT = ("dict", "map")
_TUPLE = ("tuple", "list")
_SET = ("set", "list")
_CLASS = ("type", "class")

PYTHON_PROFILE = Profile(
    builtin_names=frozenset(dir(builtins)),
    builtin_classes=frozenset(
        name for name in dir(builtins) if isinstance(getattr(builtins, name), type)
    ),
    pure_builtins=frozenset(
        {
            "len",
            "isinstance",
            "issubclass",
            "str",
            "int",
            "float",
            "bool",
            "min",
            "max",
            "sorted",
            "abs",
            "round",
            "tuple",
            "list",
            "dict",
            "set",
            "frozenset",
            "repr",
            "hash",
            "type",
            "getattr",
            "hasattr",
            "range",
            "enumerate",
            "zip",
            "reversed",
            "any",
            "all",
            "sum",
            "map",
            "filter",
            "callable",
            "chr",
            "ord",
            "hex",
            "bin",
            "oct",
            "divmod",
            "pow",
            "format",
            "bytes",
            "slice",
            "iter",
            "id",
            "object",
            "complex",
            "ascii",
            "vars",
            "dir",
        }
    ),
    pure_methods=frozenset(
        {
            "get",
            "items",
            "keys",
            "values",
            "lower",
            "upper",
            "startswith",
            "endswith",
            "split",
            "rsplit",
            "join",
            "format",
            "copy",
            "strip",
            "lstrip",
            "rstrip",
            "replace",
            "encode",
            "decode",
            "count",
            "index",
            "find",
            "rfind",
            "splitlines",
            "partition",
            "rpartition",
            "isdigit",
            "isalpha",
            "isalnum",
            "isnumeric",
            "isspace",
            "islower",
            "isupper",
            "casefold",
            "title",
            "capitalize",
            "zfill",
            "ljust",
            "rjust",
            "center",
            "removeprefix",
            "removesuffix",
            "total_seconds",
            "isoformat",
            "timestamp",
            "union",
            "intersection",
            "difference",
            "issubset",
            "issuperset",
            "symmetric_difference",
            "most_common",
            "model_dump",
            "model_copy",
            "model_dump_json",
            "to_json",
            "as_integer_ratio",
            "bit_length",
        }
    ),
    pure_externals=frozenset(
        {
            "dataclasses.replace",
            "dataclasses.asdict",
            "dataclasses.astuple",
            "dataclasses.fields",
            "dataclasses.field",
            "dataclasses.is_dataclass",
            "typing.cast",
            "copy.copy",
            "copy.deepcopy",
            "functools.partial",
            "functools.reduce",
            "os.path.join",
            "os.path.basename",
            "os.path.dirname",
            "os.path.splitext",
            "os.path.normpath",
            "json.dumps",
            "json.loads",
            "datetime.timedelta",
            "datetime.datetime",
            "datetime.date",
            "datetime.time",
            "datetime.timezone",
            "collections.namedtuple",
            "collections.defaultdict",
            "collections.deque",
            "collections.Counter",
            "collections.OrderedDict",
        }
    ),
    pure_external_modules=frozenset(
        {
            "math",
            "cmath",
            "operator",
            "itertools",
            "statistics",
            "numpy",
            "re",
            "string",
            "textwrap",
            "fractions",
            "decimal",
        }
    ),
    builtin_parameters={
        "len": ("obj",),
        "isinstance": ("obj", "type"),
        "issubclass": ("cls", "type"),
        "getattr": ("obj", "name", "default"),
        "hasattr": ("obj", "name"),
        "setattr": ("obj", "name", "value"),
        "str": ("value",),
        "int": ("value",),
        "float": ("value",),
        "bool": ("value",),
        "repr": ("value",),
        "abs": ("value",),
        "round": ("number", "ndigits"),
        "next": ("iterator", "default"),
    },
    builtin_results={
        "len": _INT,
        "int": _INT,
        "round": _INT,
        "hash": _INT,
        "id": _INT,
        "ord": _INT,
        "float": _FLOAT,
        "str": _STR,
        "repr": _STR,
        "format": _STR,
        "chr": _STR,
        "hex": _STR,
        "bin": _STR,
        "oct": _STR,
        "ascii": _STR,
        "bool": _BOOL,
        "isinstance": _BOOL,
        "issubclass": _BOOL,
        "hasattr": _BOOL,
        "callable": _BOOL,
        "any": _BOOL,
        "all": _BOOL,
        "list": _LIST,
        "sorted": _LIST,
        "tuple": _TUPLE,
        "set": _SET,
        "frozenset": _SET,
        "range": _LIST,
        "enumerate": _LIST,
        "zip": _LIST,
        "reversed": _LIST,
        "map": _LIST,
        "filter": _LIST,
        "dict": _DICT,
        "bytes": _BYTES,
        "type": _CLASS,
    },
    method_results={
        **{
            name: _STR
            for name in (
                "lower",
                "upper",
                "strip",
                "lstrip",
                "rstrip",
                "join",
                "format",
                "casefold",
                "title",
                "capitalize",
                "zfill",
                "ljust",
                "rjust",
                "center",
                "removeprefix",
                "removesuffix",
                "isoformat",
                "decode",
                "model_dump_json",
            )
        },
        **{
            name: _BOOL
            for name in (
                "startswith",
                "endswith",
                "isdigit",
                "isalpha",
                "isalnum",
                "isnumeric",
                "isspace",
                "islower",
                "isupper",
                "issubset",
                "issuperset",
            )
        },
        **{
            name: _LIST
            for name in (
                "split",
                "rsplit",
                "splitlines",
                "items",
                "keys",
                "values",
                "partition",
                "rpartition",
                "most_common",
            )
        },
        **{name: _INT for name in ("count", "index", "find", "rfind", "bit_length")},
        "encode": _BYTES,
        "total_seconds": _FLOAT,
        "timestamp": _FLOAT,
        "model_dump": _DICT,
    },
    same_type_methods=frozenset(
        {
            "copy",
            "replace",
            "model_copy",
            "union",
            "intersection",
            "difference",
            "symmetric_difference",
        }
    ),
    numeric_modules=frozenset({"math", "numpy", "cmath", "statistics"}),
    stdlib_modules=frozenset(sys.stdlib_module_names),
    none_text="None",
    receiver_names=frozenset({"self", "cls"}),
    instance_receiver="self",
    constructor_name="__init__",
    comprehensions={
        "list": ("List comprehension", "list", "list"),
        "set": ("Set comprehension", "set", "list"),
        "dict": ("Dict comprehension", "dict", "map"),
        "generator": ("Generator", "list", "list"),
    },
    types=PYTHON_TYPES,
    sequence_kinds={"tuple": _TUPLE, "list": _LIST, "set": _SET},
    variadic_label="tuple[{}, ...]",
    keywords_label="dict[str, {}]",
)

PYTHON_SYNTAX = Syntax(
    operators={
        "or": ("or", 1),
        "and": ("and", 2),
        "|": ("|", 5),
        "^": ("^", 6),
        "&": ("&", 7),
        "<<": ("<<", 8),
        ">>": (">>", 8),
        "+": ("+", 9),
        "-": ("-", 9),
        "*": ("*", 10),
        "/": ("/", 10),
        "//": ("//", 10),
        "%": ("%", 10),
        "@": ("@", 10),
        "**": ("**", 12),
    },
    comparisons={
        "==": "==",
        "!=": "!=",
        "<": "<",
        "<=": "<=",
        ">": ">",
        ">=": ">=",
        "is": "is",
        "is not": "is not",
        "in": "in",
        "not in": "not in",
    },
    compare_precedence=4,
    unary_prefixes={"not": "not ", "-": "-", "+": "+", "~": "~"},
    unary_precedence={"not": 3},
    keyword_separator="=",
    conditional_first=False,
    unchained_operators=frozenset({"**"}),
)

_BINARY: dict[type[ast.operator], str] = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.Mod: "%",
    ast.Pow: "**",
    ast.MatMult: "@",
    ast.LShift: "<<",
    ast.RShift: ">>",
    ast.BitOr: "|",
    ast.BitAnd: "&",
    ast.BitXor: "^",
}
_COMPARE: dict[type[ast.cmpop], str] = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Is: "is",
    ast.IsNot: "is not",
    ast.In: "in",
    ast.NotIn: "not in",
}
_UNARY: dict[type[ast.unaryop], str] = {
    ast.Not: "not",
    ast.USub: "-",
    ast.UAdd: "+",
    ast.Invert: "~",
}
_COMPREHENSION_KINDS: dict[type[ast.expr], str] = {
    ast.ListComp: "list",
    ast.SetComp: "set",
    ast.DictComp: "dict",
    ast.GeneratorExp: "generator",
}
_SEQUENCE_KINDS: dict[type[ast.expr], str] = {
    ast.Tuple: "tuple",
    ast.List: "list",
    ast.Set: "set",
}
_STATIC_DECORATORS = frozenset({"staticmethod"})
_CLASS_DECORATORS = frozenset({"classmethod"})
_PROPERTY_DECORATORS = frozenset({"property", "cached_property"})


class Python(Language):
    name = "python"
    extensions = (".py",)
    profile = PYTHON_PROFILE
    syntax = PYTHON_SYNTAX

    def module_name(self, path: str) -> str:
        parts = stem_parts(path, self.extensions)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts)

    def is_package_init(self, path: str) -> bool:
        return path.endswith("__init__.py")

    def lower(self, path: str, name: str, source: str, locate: Locate) -> Lowered:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source, filename=path)
        package = name if self.is_package_init(path) else name.rpartition(".")[0]
        lowering = _Lowering(package)
        body = lowering.block(tree.body)
        code = m.ModuleCode(
            body=body,
            doc=ast.get_docstring(tree),
            doc_lines=_doc_lines(tree.body),
            language=self,
        )
        return Lowered(code, lowering.imports)

    def text(self, node: m.Node) -> str:
        origin = node.origin
        if isinstance(origin, ast.AST):
            return ast.unparse(origin)
        if isinstance(origin, str):
            return origin
        return ""

    def text_with(self, node: m.Node, replacements: Mapping[m.Node, str]) -> str:
        origin = node.origin
        if not isinstance(origin, ast.AST):
            return replacements.get(node) or self.text(node)
        names = {
            id(key.origin): name
            for key, name in replacements.items()
            if isinstance(key.origin, ast.AST)
        }
        memo: dict[int, Any] = {}
        copied = copy.deepcopy(origin, memo)
        renamed = {id(memo[key]): name for key, name in names.items() if key in memo}
        result: ast.AST = _Renamer(renamed).visit(copied)
        return ast.unparse(result)

    def literal_text(self, value: object) -> str:
        if value is ...:
            return "..."
        if value is None or isinstance(value, (str, bytes, bool, int, float, complex)):
            return ast.unparse(ast.Constant(value))
        return repr(value)

    def is_constant(self, statement: m.Assign) -> bool:
        if len(statement.targets) != 1:
            return False
        target = statement.targets[0]
        if not isinstance(target, m.Name):
            return False
        if statement.annotation is not None:
            return statement.value is not None
        bare = target.id.lstrip("_")
        return bool(bare) and bare.isupper()


class _Renamer(ast.NodeTransformer):
    def __init__(self, names: dict[int, str]) -> None:
        self.names = names

    def visit(self, node: ast.AST) -> Any:
        name = self.names.get(id(node))
        return ast.Name(name) if name is not None else super().visit(node)


class _Lowering:
    def __init__(self, package: str) -> None:
        self.package = package
        self.imports: dict[str, ImportBinding] = {}

    def block(self, statements: Sequence[ast.stmt]) -> list[m.Stmt]:
        return [self.statement(statement) for statement in statements]

    def statement(self, node: ast.stmt) -> m.Stmt:
        line, end = _span(node)
        if isinstance(node, ast.Expr):
            return m.ExprStmt(line, end, self.expr(node.value), origin=node)
        if isinstance(node, ast.Assign):
            return m.Assign(
                line,
                end,
                [self.expr(target) for target in node.targets],
                self.expr(node.value),
                origin=node,
            )
        if isinstance(node, ast.AnnAssign):
            return m.Assign(
                line,
                end,
                [self.expr(node.target)],
                self.optional(node.value),
                annotation=self.type_expr(node.annotation),
                origin=node,
            )
        if isinstance(node, ast.AugAssign):
            return m.AugAssign(
                line,
                end,
                self.expr(node.target),
                _BINARY.get(type(node.op), "?"),
                self.expr(node.value),
                origin=node,
            )
        if isinstance(node, ast.Return):
            return m.Return(line, end, self.optional(node.value), origin=node)
        if isinstance(node, ast.If):
            return m.If(
                line,
                end,
                self.expr(node.test),
                self.block(node.body),
                self.block(node.orelse),
                origin=node,
            )
        if isinstance(node, (ast.For, ast.AsyncFor)):
            return m.For(
                line,
                end,
                self.expr(node.target),
                self.expr(node.iter),
                self.block(node.body),
                self.block(node.orelse),
                is_async=isinstance(node, ast.AsyncFor),
                origin=node,
            )
        if isinstance(node, ast.While):
            return m.While(
                line,
                end,
                self.expr(node.test),
                self.block(node.body),
                self.block(node.orelse),
                origin=node,
            )
        if isinstance(node, (ast.With, ast.AsyncWith)):
            return m.With(
                line,
                end,
                [
                    m.WithItem(
                        *_span(item.context_expr),
                        self.expr(item.context_expr),
                        self.optional(item.optional_vars),
                        origin=item,
                    )
                    for item in node.items
                ],
                self.block(node.body),
                is_async=isinstance(node, ast.AsyncWith),
                origin=node,
            )
        if isinstance(node, (ast.Try, ast.TryStar)):
            return m.Try(
                line,
                end,
                self.block(node.body),
                [
                    m.Handler(
                        *_span(handler),
                        self.optional(handler.type),
                        handler.name,
                        self.block(handler.body),
                        origin=handler,
                    )
                    for handler in node.handlers
                ],
                self.block(node.orelse),
                self.block(node.finalbody),
                origin=node,
            )
        if isinstance(node, ast.Raise):
            return m.Raise(
                line,
                end,
                self.optional(node.exc),
                self.optional(node.cause),
                origin=node,
            )
        if isinstance(node, ast.Assert):
            return m.Assert(
                line, end, self.expr(node.test), self.optional(node.msg), origin=node
            )
        if isinstance(node, ast.Delete):
            return m.Delete(
                line, end, [self.expr(target) for target in node.targets], origin=node
            )
        if isinstance(node, ast.Break):
            return m.Break(line, end, origin=node)
        if isinstance(node, ast.Continue):
            return m.Continue(line, end, origin=node)
        if isinstance(node, ast.Pass) or type(node).__name__ == "TypeAlias":
            return m.Pass(line, end, origin=node)
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            return m.Global(line, end, list(node.names), origin=node)
        if isinstance(node, ast.Match):
            return m.Match(
                line,
                end,
                self.expr(node.subject),
                [
                    m.Case(
                        *_span(case.pattern),
                        m.Pattern(
                            *_span(case.pattern),
                            _pattern_captures(case.pattern),
                            isinstance(case.pattern, ast.MatchAs)
                            and case.pattern.pattern is None,
                            [
                                self.expr(reference)
                                for reference in _pattern_references(case.pattern)
                            ],
                            origin=case.pattern,
                        ),
                        self.optional(case.guard),
                        self.block(case.body),
                        origin=case,
                    )
                    for case in node.cases
                ],
                origin=node,
            )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return m.FunctionDef(line, end, self.function(node), origin=node)
        if isinstance(node, ast.ClassDef):
            return m.ClassDef(line, end, self.cls(node), origin=node)
        if isinstance(node, ast.Import):
            return self.import_statement(node)
        if isinstance(node, ast.ImportFrom):
            return self.import_from(node)
        return m.OtherStmt(line, end, origin=node)

    def function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> m.FunctionDecl:
        line, end = _span(node)
        decorators = [self.expr(decorator) for decorator in node.decorator_list]
        names = {
            (m.dotted_name(_decorated(decorator)) or "").rsplit(".", 1)[-1]
            for decorator in decorators
        }
        return m.FunctionDecl(
            line,
            end,
            node.name,
            self.parameters(node.args),
            self.type_expr(node.returns) if node.returns is not None else None,
            self.block(node.body),
            decorators=decorators,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            doc=ast.get_docstring(node),
            doc_lines=_doc_lines(node.body),
            start_line=min([line] + [d.lineno for d in node.decorator_list]),
            binding=(
                "static"
                if names & _STATIC_DECORATORS
                else "class" if names & _CLASS_DECORATORS else "instance"
            ),
            is_property=bool(names & _PROPERTY_DECORATORS),
            is_overload=any(
                m.dotted_name(decorator) in ("overload", "typing.overload")
                for decorator in decorators
            ),
            is_constructor=node.name == "__init__",
            origin=node,
        )

    def cls(self, node: ast.ClassDef) -> m.ClassDecl:
        line, end = _span(node)
        return m.ClassDecl(
            line,
            end,
            node.name,
            [self.expr(base) for base in node.bases],
            self.block(node.body),
            decorators=[self.expr(decorator) for decorator in node.decorator_list],
            doc=ast.get_docstring(node),
            doc_lines=_doc_lines(node.body),
            start_line=min([line] + [d.lineno for d in node.decorator_list]),
            origin=node,
        )

    def parameters(self, arguments: ast.arguments) -> list[m.Parameter]:
        positional = [*arguments.posonlyargs, *arguments.args]
        defaults: list[ast.expr | None] = [None] * (
            len(positional) - len(arguments.defaults)
        ) + list(arguments.defaults)
        out = [
            self.parameter(
                argument,
                default,
                (
                    "positional_only"
                    if index < len(arguments.posonlyargs)
                    else "positional"
                ),
            )
            for index, (argument, default) in enumerate(zip(positional, defaults))
        ]
        if arguments.vararg is not None:
            out.append(self.parameter(arguments.vararg, None, "variadic"))
        out += [
            self.parameter(argument, default, "keyword_only")
            for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults)
        ]
        if arguments.kwarg is not None:
            out.append(self.parameter(arguments.kwarg, None, "variadic_keyword"))
        return out

    def parameter(
        self, argument: ast.arg, default: ast.expr | None, kind: str
    ) -> m.Parameter:
        return m.Parameter(
            *_span(argument),
            argument.arg,
            (
                self.type_expr(argument.annotation)
                if argument.annotation is not None
                else None
            ),
            self.optional(default),
            kind,
            origin=argument,
        )

    def import_statement(self, node: ast.Import) -> m.Stmt:
        return m.Import(
            *_span(node),
            None,
            [m.ImportName(*_span(a), a.name, a.asname, origin=a) for a in node.names],
            whole=True,
            origin=node,
        )

    def import_from(self, node: ast.ImportFrom) -> m.Stmt:
        base = self.from_base(node)
        return m.Import(
            *_span(node),
            base,
            [m.ImportName(*_span(a), a.name, a.asname, origin=a) for a in node.names],
            level=node.level,
            whole=False,
            origin=node,
        )

    def from_base(self, node: ast.ImportFrom) -> str | None:
        if node.level == 0:
            return node.module or ""
        package_parts = self.package.split(".") if self.package else []
        if node.level - 1 > len(package_parts):
            return None
        kept = package_parts[: len(package_parts) - (node.level - 1)]
        if node.module:
            kept.append(node.module)
        return ".".join(kept)

    def optional(self, node: ast.expr | None) -> m.Expr | None:
        return self.expr(node) if node is not None else None

    def expr(self, node: ast.expr) -> m.Expr:
        line, end = _span(node)
        if isinstance(node, ast.Name):
            return m.Name(
                line,
                end,
                node.id,
                isinstance(node.ctx, (ast.Store, ast.Del)),
                origin=node,
            )
        if isinstance(node, ast.Attribute):
            return m.Member(
                line,
                end,
                self.expr(node.value),
                node.attr,
                isinstance(node.ctx, ast.Store),
                origin=node,
            )
        if isinstance(node, ast.Call):
            return m.Call(
                line,
                end,
                self.expr(node.func),
                [self.expr(argument) for argument in node.args],
                [
                    m.Keyword(
                        *_span(keyword.value),
                        keyword.arg,
                        self.expr(keyword.value),
                        origin=keyword,
                    )
                    for keyword in node.keywords
                ],
                origin=node,
            )
        if isinstance(node, ast.Constant):
            return m.Literal(line, end, node.value, origin=node)
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return m.Sequence(
                line,
                end,
                _SEQUENCE_KINDS[type(node)],
                [self.expr(element) for element in node.elts],
                isinstance(getattr(node, "ctx", None), ast.Store),
                origin=node,
            )
        if isinstance(node, ast.Dict):
            return m.Mapping(
                line,
                end,
                [self.expr(key) if key is not None else None for key in node.keys],
                [self.expr(value) for value in node.values],
                origin=node,
            )
        if isinstance(node, ast.BinOp):
            return m.Binary(
                line,
                end,
                _BINARY.get(type(node.op), "?"),
                self.expr(node.left),
                self.expr(node.right),
                origin=node,
            )
        if isinstance(node, ast.UnaryOp):
            return m.Unary(
                line,
                end,
                _UNARY.get(type(node.op), "?"),
                self.expr(node.operand),
                origin=node,
            )
        if isinstance(node, ast.Compare):
            return m.Compare(
                line,
                end,
                self.expr(node.left),
                [_COMPARE.get(type(op), "?") for op in node.ops],
                [self.expr(comparator) for comparator in node.comparators],
                origin=node,
            )
        if isinstance(node, ast.BoolOp):
            return m.Logical(
                line,
                end,
                "and" if isinstance(node.op, ast.And) else "or",
                [self.expr(value) for value in node.values],
                origin=node,
            )
        if isinstance(node, ast.IfExp):
            return m.Conditional(
                line,
                end,
                self.expr(node.test),
                self.expr(node.body),
                self.expr(node.orelse),
                origin=node,
            )
        if isinstance(node, ast.Subscript):
            return m.Subscript(
                line,
                end,
                self.expr(node.value),
                self.expr(node.slice),
                isinstance(node.ctx, ast.Store),
                origin=node,
            )
        if isinstance(node, ast.Slice):
            return m.Slice(
                line,
                end,
                self.optional(node.lower),
                self.optional(node.upper),
                self.optional(node.step),
                origin=node,
            )
        if isinstance(node, ast.JoinedStr):
            return m.Template(
                line, end, [self.expr(part) for part in node.values], origin=node
            )
        if isinstance(node, ast.FormattedValue):
            return m.Interpolation(
                line,
                end,
                self.expr(node.value),
                self.optional(node.format_spec),
                origin=node,
            )
        if isinstance(node, tuple(_COMPREHENSION_KINDS)):
            return self.comprehension(node)
        if isinstance(node, ast.Lambda):
            return m.Function(
                line,
                end,
                self.parameters(node.args),
                [],
                self.expr(node.body),
                origin=node,
            )
        if isinstance(node, ast.Await):
            return m.Await(line, end, self.expr(node.value), origin=node)
        if isinstance(node, ast.Yield):
            return m.Yield(line, end, self.optional(node.value), origin=node)
        if isinstance(node, ast.YieldFrom):
            return m.Yield(line, end, self.expr(node.value), True, origin=node)
        if isinstance(node, ast.NamedExpr):
            target = self.expr(node.target)
            assert isinstance(target, m.Name)
            return m.AssignExpr(line, end, target, self.expr(node.value), origin=node)
        if isinstance(node, ast.Starred):
            return m.Spread(
                line,
                end,
                self.expr(node.value),
                isinstance(node.ctx, ast.Store),
                origin=node,
            )
        return m.OtherExpr(
            line,
            end,
            [
                self.expr(child)
                for child in ast.iter_child_nodes(node)
                if isinstance(child, ast.expr)
            ],
            origin=node,
        )

    def comprehension(self, node: ast.expr) -> m.Expr:
        line, end = _span(node)
        heads: list[m.Node]
        if isinstance(node, ast.DictComp):
            heads = [self.expr(node.key), self.expr(node.value)]
            generators = node.generators
        else:
            assert isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp))
            heads = [self.expr(node.elt)]
            generators = node.generators
        clauses: list[m.Node] = [
            m.OtherExpr(
                *_span(generator.iter),
                [
                    self.expr(generator.target),
                    self.expr(generator.iter),
                    *(self.expr(condition) for condition in generator.ifs),
                ],
                origin=generator,
            )
            for generator in generators
        ]
        bound = [
            child.id
            for generator in generators
            for child in ast.walk(generator.target)
            if isinstance(child, ast.Name)
        ]
        return m.Comprehension(
            line,
            end,
            _COMPREHENSION_KINDS[type(node)],
            [*heads, *clauses],
            bound,
            origin=node,
        )

    def type_expr(self, node: ast.expr) -> m.TypeExpr:
        line, end = _span(node)
        if isinstance(node, ast.Constant):
            parsed: m.TypeExpr | None = None
            if isinstance(node.value, str):
                try:
                    parsed = self.type_expr(ast.parse(node.value, mode="eval").body)
                except SyntaxError:
                    parsed = None
            return m.TypeLiteral(line, end, node.value, parsed, origin=node)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return m.TypeUnion(
                line,
                end,
                [self.type_expr(member) for member in _flatten_union(node)],
                origin=node,
            )
        if isinstance(node, (ast.Name, ast.Attribute)):
            dotted = _dotted(node)
            if dotted is None:
                return m.TypeOther(line, end, "Any", origin=node)
            return m.TypeName(line, end, dotted, origin=node)
        if isinstance(node, ast.Subscript):
            args = (
                list(node.slice.elts)
                if isinstance(node.slice, ast.Tuple)
                else [node.slice]
            )
            return m.TypeName(
                line,
                end,
                _dotted(node.value) or "",
                [self.type_expr(argument) for argument in args],
                origin=node,
            )
        return m.TypeOther(line, end, value=self.expr(node), origin=node)


def _decorated(decorator: m.Expr) -> m.Expr:
    return decorator.func if isinstance(decorator, m.Call) else decorator


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base is not None else None
    return None


def _span(node: ast.AST) -> tuple[int, int]:
    line = int(getattr(node, "lineno", 0) or 0)
    end = getattr(node, "end_lineno", None)
    return line, int(end) if end is not None else line


def _doc_lines(body: Sequence[ast.stmt]) -> tuple[int, int] | None:
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return _span(body[0])
    return None


def _flatten_union(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _flatten_union(node.left) + _flatten_union(node.right)
    return [node]


def _pattern_references(pattern: ast.pattern) -> Iterator[ast.expr]:
    for node in ast.walk(pattern):
        if isinstance(node, ast.pattern):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.expr):
                    yield child


def _pattern_captures(pattern: ast.pattern) -> list[str]:
    names: list[str] = []
    for node in ast.walk(pattern):
        if (
            isinstance(node, (ast.MatchAs, ast.MatchStar))
            and node.name
            and node.name not in names
        ):
            names.append(node.name)
        elif (
            isinstance(node, ast.MatchMapping) and node.rest and node.rest not in names
        ):
            names.append(node.rest)
    return names
