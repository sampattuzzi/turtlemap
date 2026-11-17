import codecs
import json
import re
from collections.abc import Iterator, Mapping, Sequence

import tree_sitter_typescript
from tree_sitter import Language as Grammar
from tree_sitter import Node as Syntax
from tree_sitter import Parser

from code_blueprints.analysis import model as m
from code_blueprints.languages.language import (
    ImportBinding,
    Language,
    Locate,
    Lowered,
    Profile,
    Syntax as Operators,
    TypeNames,
    stem_parts,
)

_TYPESCRIPT = Grammar(tree_sitter_typescript.language_typescript())
_TSX = Grammar(tree_sitter_typescript.language_tsx())

_STRING = ("string", "str")
_NUMBER = ("number", "float")
_BOOLEAN = ("boolean", "bool")
_ARRAY = ("Array", "list")
_OBJECT = ("Object", "map")

JAVASCRIPT_TYPES = TypeNames(
    scalars={
        "number": "float",
        "bigint": "int",
        "string": "str",
        "boolean": "bool",
        "void": "none",
        "undefined": "none",
        "null": "none",
        "never": "none",
        "any": "any",
        "unknown": "any",
        "object": "map",
        "symbol": "any",
        "String": "str",
        "Number": "float",
        "Boolean": "bool",
        "Date": "object",
        "RegExp": "object",
    },
    lists=frozenset({"Array", "ReadonlyArray", "Set", "ReadonlySet", "Iterable"}),
    maps=frozenset({"Map", "ReadonlyMap", "Record", "WeakMap"}),
    transparent=frozenset({"Readonly", "Partial", "Required", "NonNullable"}),
    enum_bases=frozenset(),
    struct_bases=frozenset(),
    struct_decorators=frozenset(),
    interface_bases=frozenset(),
    model_bases=frozenset(),
    optional=frozenset(),
    union=frozenset(),
    literal=frozenset(),
    callables=frozenset({"Function"}),
    class_types=frozenset(),
    awaitables=frozenset({"Promise", "PromiseLike"}),
    guards=frozenset(),
    tuples=frozenset(),
    class_variable=frozenset(),
    sequences=frozenset({"Array", "ReadonlyArray", "Set", "ReadonlySet", "Iterable"}),
    mappings=frozenset({"Map", "ReadonlyMap", "Record"}),
)

_BROWSER_GLOBALS = frozenset(
    {
        "window",
        "document",
        "console",
        "navigator",
        "location",
        "history",
        "localStorage",
        "sessionStorage",
        "performance",
        "fetch",
        "alert",
        "confirm",
        "prompt",
        "setTimeout",
        "clearTimeout",
        "setInterval",
        "clearInterval",
        "requestAnimationFrame",
        "cancelAnimationFrame",
        "queueMicrotask",
        "structuredClone",
        "getComputedStyle",
        "matchMedia",
        "globalThis",
        "process",
        "require",
        "module",
        "exports",
        "Buffer",
        "__dirname",
        "__filename",
        "crypto",
        "encodeURIComponent",
        "decodeURIComponent",
        "encodeURI",
        "decodeURI",
        "parseInt",
        "parseFloat",
        "isNaN",
        "isFinite",
        "undefined",
        "NaN",
        "Infinity",
        "Math",
        "JSON",
        "Reflect",
        "Intl",
        "Atomics",
    }
)
_BUILTIN_CLASSES = frozenset(
    {
        "Object",
        "Array",
        "String",
        "Number",
        "Boolean",
        "BigInt",
        "Symbol",
        "Function",
        "Promise",
        "Map",
        "Set",
        "WeakMap",
        "WeakSet",
        "WeakRef",
        "Date",
        "RegExp",
        "Error",
        "TypeError",
        "RangeError",
        "SyntaxError",
        "ReferenceError",
        "AggregateError",
        "Proxy",
        "URL",
        "URLSearchParams",
        "AbortController",
        "TextEncoder",
        "TextDecoder",
        "Blob",
        "File",
        "FormData",
        "Headers",
        "Request",
        "Response",
        "WebSocket",
        "EventSource",
        "Event",
        "CustomEvent",
        "EventTarget",
        "ResizeObserver",
        "MutationObserver",
        "IntersectionObserver",
        "DOMParser",
        "Image",
        "Path2D",
        "HTMLElement",
        "Element",
        "Node",
        "ArrayBuffer",
        "DataView",
        "Uint8Array",
        "Int8Array",
        "Uint16Array",
        "Int16Array",
        "Uint32Array",
        "Int32Array",
        "Float32Array",
        "Float64Array",
    }
)
_NODE_MODULES = frozenset(
    {
        "assert",
        "buffer",
        "child_process",
        "cluster",
        "crypto",
        "dgram",
        "dns",
        "events",
        "fs",
        "http",
        "http2",
        "https",
        "net",
        "os",
        "path",
        "perf_hooks",
        "process",
        "querystring",
        "readline",
        "stream",
        "string_decoder",
        "timers",
        "tls",
        "url",
        "util",
        "v8",
        "vm",
        "worker_threads",
        "zlib",
    }
)

JAVASCRIPT_PROFILE = Profile(
    builtin_names=_BROWSER_GLOBALS | _BUILTIN_CLASSES,
    builtin_classes=_BUILTIN_CLASSES,
    pure_builtins=frozenset(
        {
            "parseInt",
            "parseFloat",
            "isNaN",
            "isFinite",
            "encodeURIComponent",
            "decodeURIComponent",
            "String",
            "Number",
            "Boolean",
            "BigInt",
            "Math",
            "JSON",
            "structuredClone",
        }
    ),
    pure_methods=frozenset(
        {
            "map",
            "filter",
            "reduce",
            "reduceRight",
            "slice",
            "concat",
            "join",
            "includes",
            "indexOf",
            "lastIndexOf",
            "find",
            "findIndex",
            "findLast",
            "findLastIndex",
            "some",
            "every",
            "flat",
            "flatMap",
            "at",
            "keys",
            "values",
            "entries",
            "get",
            "has",
            "trim",
            "trimStart",
            "trimEnd",
            "toLowerCase",
            "toUpperCase",
            "startsWith",
            "endsWith",
            "split",
            "replace",
            "replaceAll",
            "padStart",
            "padEnd",
            "repeat",
            "toFixed",
            "toString",
            "toISOString",
            "localeCompare",
            "charAt",
            "charCodeAt",
            "substring",
            "match",
            "test",
            "getTime",
            "toSorted",
            "toReversed",
            "with",
        }
    ),
    pure_externals=frozenset(),
    pure_external_modules=frozenset({"path", "node:path", "url"}),
    builtin_parameters={
        "parseInt": ("string", "radix"),
        "parseFloat": ("string",),
        "setTimeout": ("handler", "delay"),
        "setInterval": ("handler", "delay"),
        "String": ("value",),
        "Number": ("value",),
        "Boolean": ("value",),
    },
    builtin_results={
        "parseInt": _NUMBER,
        "parseFloat": _NUMBER,
        "Number": _NUMBER,
        "isNaN": _BOOLEAN,
        "isFinite": _BOOLEAN,
        "Boolean": _BOOLEAN,
        "String": _STRING,
        "encodeURIComponent": _STRING,
        "decodeURIComponent": _STRING,
        "JSON.stringify": _STRING,
        "Array.isArray": _BOOLEAN,
        "Array.from": _ARRAY,
        "Array.of": _ARRAY,
        "Object.keys": _ARRAY,
        "Object.values": _ARRAY,
        "Object.entries": _ARRAY,
        "Object.assign": _OBJECT,
        "Object.fromEntries": _OBJECT,
        "Math.max": _NUMBER,
        "Math.min": _NUMBER,
        "Math.abs": _NUMBER,
        "Math.round": _NUMBER,
        "Math.floor": _NUMBER,
        "Math.ceil": _NUMBER,
        "Math.sqrt": _NUMBER,
        "Math.hypot": _NUMBER,
        "Math.random": _NUMBER,
        "Math.pow": _NUMBER,
        "Math.sign": _NUMBER,
        "Math.trunc": _NUMBER,
        "Date.now": _NUMBER,
    },
    method_results={
        **{
            name: _STRING
            for name in (
                "join",
                "trim",
                "trimStart",
                "trimEnd",
                "toLowerCase",
                "toUpperCase",
                "padStart",
                "padEnd",
                "repeat",
                "toFixed",
                "toString",
                "toISOString",
                "charAt",
                "substring",
                "replace",
                "replaceAll",
            )
        },
        **{
            name: _BOOLEAN
            for name in (
                "includes",
                "startsWith",
                "endsWith",
                "some",
                "every",
                "has",
                "test",
            )
        },
        **{
            name: _ARRAY
            for name in ("map", "filter", "split", "flat", "flatMap", "keys", "values")
        },
        **{
            name: _NUMBER
            for name in (
                "indexOf",
                "lastIndexOf",
                "findIndex",
                "localeCompare",
                "charCodeAt",
                "getTime",
            )
        },
    },
    same_type_methods=frozenset({"slice", "concat", "toSorted", "toReversed", "with"}),
    numeric_modules=frozenset({"Math"}),
    stdlib_modules=_NODE_MODULES | frozenset(f"node:{name}" for name in _NODE_MODULES),
    none_text="undefined",
    receiver_names=frozenset({"this"}),
    instance_receiver="this",
    constructor_name="constructor",
    comprehensions={},
    types=JAVASCRIPT_TYPES,
    super_name="super",
    default_exception="Error",
    sequence_kinds={"array": _ARRAY},
    mapping_kind=_OBJECT,
    function_title="Arrow function",
    variadic_label="{}",
    keywords_label="Record<string, {}>",
    callable_label="Function",
    class_label="class",
    handler_word="catch",
    match_title="Switch",
    spread_prefix="...",
    mapping_spread_prefix="...",
    follows_star_imports=True,
    optional_label="{} | undefined",
    literal_labels={
        "int": "number",
        "float": "number",
        "str": "string",
        "bool": "boolean",
        "bytes": "Uint8Array",
        "None": "undefined",
    },
)

JAVASCRIPT_SYNTAX = Operators(
    operators={
        "or": ("||", 1),
        "??": ("??", 1),
        "and": ("&&", 2),
        "|": ("|", 5),
        "^": ("^", 6),
        "&": ("&", 7),
        "<<": ("<<", 8),
        ">>": (">>", 8),
        ">>>": (">>>", 8),
        "+": ("+", 9),
        "-": ("-", 9),
        "*": ("*", 10),
        "/": ("/", 10),
        "%": ("%", 10),
        "**": ("**", 12),
    },
    comparisons={
        "===": "===",
        "!==": "!==",
        "==": "==",
        "!=": "!=",
        "<": "<",
        "<=": "<=",
        ">": ">",
        ">=": ">=",
        "in": "in",
        "instanceof": "instanceof",
    },
    compare_precedence=4,
    unary_prefixes={
        "not": "!",
        "-": "-",
        "+": "+",
        "~": "~",
        "typeof": "typeof ",
        "void": "void ",
        "delete": "delete ",
    },
    unary_precedence={},
    keyword_separator="=",
    conditional_first=True,
    unchained_operators=frozenset({"**"}),
    brackets={"array": ("[", "]")},
)

_LOGICAL = {"&&": "and", "||": "or", "??": "??"}
_COMPARISONS = frozenset(JAVASCRIPT_SYNTAX.comparisons)
_UNARY = {"!": "not", "-": "-", "+": "+", "~": "~", "typeof": "typeof", "void": "void"}
_FUNCTIONS = frozenset(
    {"arrow_function", "function_expression", "function", "generator_function"}
)
_DECLARATIONS = frozenset({"lexical_declaration", "variable_declaration"})
_CLASSES = frozenset({"class_declaration", "abstract_class_declaration", "class"})
_SKIPPED = frozenset({"comment", "html_comment"})
_EXCLUDED_SUFFIXES = (".d.ts", ".d.mts", ".d.cts", ".min.js", ".bundle.js")
_NAME_CHARACTERS = re.compile(r"[.:\s]+")
_WRAPPER_RECEIVER = re.compile(r"^[A-Z]")


class JavaScript(Language):
    name = "javascript"
    extensions = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
    comment_prefix = "//"
    reads_other_files = True
    profile = JAVASCRIPT_PROFILE
    syntax = JAVASCRIPT_SYNTAX

    def includes(self, path: str) -> bool:
        return not path.endswith(_EXCLUDED_SUFFIXES)

    def module_name(self, path: str) -> str:
        return ".".join(
            part.replace(".", "-") for part in stem_parts(path, self.extensions)
        )

    def is_package_init(self, path: str) -> bool:
        return False

    def lower(self, path: str, name: str, source: str, locate: Locate) -> Lowered:
        data = source.encode("utf-8")
        grammar = _TYPESCRIPT if path.endswith((".ts", ".mts", ".cts")) else _TSX
        tree = Parser(grammar).parse(data)
        root = tree.root_node
        if root.has_error and _error_ratio(root) > 0.2:
            raise SyntaxError(f"could not parse {path}")
        lowering = _Lowering(self, path, name, locate)
        body = lowering.module(root)
        doc, doc_lines = _leading_doc(root)
        code = m.ModuleCode(
            body=body,
            doc=doc,
            doc_lines=doc_lines,
            language=self,
            is_script=lowering.is_script(path, data),
        )
        return Lowered(code, lowering.bindings)

    def text(self, node: m.Node) -> str:
        origin = node.origin
        if isinstance(origin, Syntax):
            return _collapse(_decode(origin.text))
        if isinstance(origin, str):
            return origin
        return ""

    def text_with(self, node: m.Node, replacements: Mapping[m.Node, str]) -> str:
        origin = node.origin
        if not isinstance(origin, Syntax):
            return replacements.get(node) or self.text(node)
        start, end = origin.start_byte, origin.end_byte
        spans = sorted(
            (
                (key.origin.start_byte, key.origin.end_byte, name)
                for key, name in replacements.items()
                if isinstance(key.origin, Syntax)
                and start <= key.origin.start_byte
                and key.origin.end_byte <= end
            ),
            key=lambda span: (span[0], -span[1]),
        )
        data = origin.text or b""
        pieces: list[str] = []
        cursor = start
        for span_start, span_end, name in spans:
            if span_start < cursor:
                continue
            pieces.append(_decode(data[cursor - start : span_start - start]))
            pieces.append(name)
            cursor = span_end
        pieces.append(_decode(data[cursor - start :]))
        return _collapse("".join(pieces))

    def literal_text(self, value: object) -> str:
        if value is None:
            return "undefined"
        if value is True:
            return "true"
        if value is False:
            return "false"
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        return repr(value)

    def is_constant(self, statement: m.Assign) -> bool:
        if len(statement.targets) != 1 or statement.declaration != "const":
            return False
        target = statement.targets[0]
        if not isinstance(target, m.Name):
            return False
        bare = target.id.lstrip("_$")
        return bool(bare) and (bare.isupper() or _is_data(statement.value))

    def case_label(self, pattern: m.Pattern) -> str:
        if pattern.catch_all:
            return "default"
        return "case " + ", ".join(self.text(value) for value in pattern.references)

    def parse_errors(self) -> tuple[type[Exception], ...]:
        return (SyntaxError, ValueError, RecursionError)


class _Lowering:
    def __init__(
        self, language: JavaScript, path: str, name: str, locate: Locate
    ) -> None:
        self.language = language
        self.path = path
        self.name = name
        self.locate = locate
        self.bindings: dict[str, ImportBinding] = {}
        self.hoisted: list[m.Stmt] = []
        self.scopes: list[set[str]] = [set()]
        self.context: list[str] = []
        self.receivers: list[str | None] = [None]
        self.has_module_syntax = False

    def is_script(self, path: str, data: bytes) -> bool:
        if self.has_module_syntax or path.endswith((".mjs", ".cjs")):
            return False
        return b"require(" not in data and b"exports" not in data

    def module(self, root: Syntax) -> list[m.Stmt]:
        return self.block(_named(root))

    def block(self, nodes: Sequence[Syntax]) -> list[m.Stmt]:
        out: list[m.Stmt] = []
        for node in nodes:
            saved = self.hoisted
            self.hoisted = []
            lowered = self.statement(node)
            out.extend(self.hoisted)
            out.extend(lowered)
            self.hoisted = saved
        return out

    def body(self, node: Syntax | None) -> list[m.Stmt]:
        if node is None:
            return []
        if node.type == "statement_block":
            return self.block(_named(node))
        return self.block([node])

    def statement(self, node: Syntax) -> list[m.Stmt]:
        kind = node.type
        line, end = _span(node)
        if kind == "expression_statement":
            inner = _first(node)
            return self.expression_statement(inner) if inner is not None else []
        if kind in _DECLARATIONS:
            return self.declaration(node)
        if kind in (
            "function_declaration",
            "generator_function_declaration",
            "function_signature",
        ):
            return [self.function_def(node, _name_text(node) or "default")]
        if kind in _CLASSES:
            return [self.class_def(node, _name_text(node) or "default")]
        if kind == "interface_declaration":
            return [self.interface(node)]
        if kind == "enum_declaration":
            return [self.enum(node)]
        if kind == "type_alias_declaration":
            return self.type_alias(node)
        if kind == "import_statement":
            self.has_module_syntax = True
            return self.import_statement(node)
        if kind == "export_statement":
            self.has_module_syntax = True
            return self.export_statement(node)
        if kind == "return_statement":
            value = _first(node)
            return [
                m.Return(
                    line,
                    end,
                    self.expr(value) if value is not None else None,
                    origin=node,
                )
            ]
        if kind == "throw_statement":
            value = _first(node)
            return [
                m.Raise(line, end, self.expr(value) if value else None, origin=node)
            ]
        if kind == "if_statement":
            return [self.if_statement(node)]
        if kind == "for_statement":
            return self.for_statement(node)
        if kind == "for_in_statement":
            return [self.for_in(node)]
        if kind == "while_statement":
            return [
                m.While(
                    line,
                    end,
                    self.expr(_field(node, "condition")),
                    self.body(node.child_by_field_name("body")),
                    origin=node,
                )
            ]
        if kind == "do_statement":
            return [
                m.While(
                    line,
                    end,
                    self.expr(_field(node, "condition")),
                    self.body(node.child_by_field_name("body")),
                    origin=node,
                )
            ]
        if kind == "try_statement":
            return [self.try_statement(node)]
        if kind == "switch_statement":
            return [self.switch(node)]
        if kind == "break_statement":
            return [m.Break(line, end, origin=node)]
        if kind == "continue_statement":
            return [m.Continue(line, end, origin=node)]
        if kind == "statement_block":
            return self.block(_named(node))
        if kind == "labeled_statement":
            inner = node.child_by_field_name("body")
            return self.statement(inner) if inner is not None else []
        if kind in ("empty_statement", "debugger_statement", "comment"):
            return []
        if kind in ("ambient_declaration", "module", "internal_module"):
            inner = node.child_by_field_name("body")
            return self.body(inner) if inner is not None else []
        return [
            m.OtherStmt(
                line,
                end,
                [self.expr(child) for child in _named(node) if _is_expression(child)],
                origin=node,
            )
        ]

    def expression_statement(self, node: Syntax) -> list[m.Stmt]:
        line, end = _span(node)
        node = _unwrap(node)
        kind = node.type
        if kind == "assignment_expression":
            targets: list[Syntax] = []
            current = node
            while current.type == "assignment_expression":
                targets.append(_field(current, "left"))
                current = _unwrap(_field(current, "right"))
            hoisted = self.hoisted_assignment(targets[-1], current)
            if hoisted is not None:
                return hoisted
            value = self.expr(current)
            return [
                m.Assign(
                    line,
                    end,
                    [self.target(target) for target in targets],
                    value,
                    origin=node,
                )
            ]
        if kind == "augmented_assignment_expression":
            operator = _operator(node).removesuffix("=")
            return [
                m.AugAssign(
                    line,
                    end,
                    self.target(_field(node, "left")),
                    _LOGICAL.get(operator, operator),
                    self.expr(_field(node, "right")),
                    origin=node,
                )
            ]
        if kind == "update_expression":
            argument = _field(node, "argument")
            operator = "+" if "++" in _operator(node) else "-"
            return [
                m.AugAssign(
                    line,
                    end,
                    self.target(argument),
                    operator,
                    m.Literal(line, end, 1, origin="1"),
                    origin=node,
                )
            ]
        if kind == "unary_expression" and _operator(node) == "delete":
            return [
                m.Delete(
                    line, end, [self.target(_field(node, "argument"))], origin=node
                )
            ]
        if kind == "call_expression":
            imported = self.require_call(node, None)
            if imported is not None:
                return imported
        return [m.ExprStmt(line, end, self.expr(node), origin=node)]

    def hoisted_assignment(self, target: Syntax, value: Syntax) -> list[m.Stmt] | None:
        if value.type not in _FUNCTIONS or _is_expression_arrow(value):
            return None
        name = _last_segment(target)
        if name is None:
            return None
        function = self.function_value(value, name)
        line, end = _span(target)
        return [m.Assign(line, end, [self.target(target)], function, origin=target)]

    def declaration(self, node: Syntax) -> list[m.Stmt]:
        kind = _keyword(node) or "var"
        out: list[m.Stmt] = []
        for declarator in node.named_children:
            if declarator.type != "variable_declarator":
                continue
            out.extend(self.declarator(declarator, kind))
        return out

    def declarator(self, node: Syntax, kind: str) -> list[m.Stmt]:
        line, end = _span(node)
        name_node = _field(node, "name")
        value_node = node.child_by_field_name("value")
        value = _unwrap(value_node) if value_node is not None else None
        type_node = node.child_by_field_name("type")
        annotation = self.type_annotation(type_node)
        if value is not None and name_node.type == "identifier":
            name = _decode(name_node.text)
            if value.type in _FUNCTIONS:
                return [self.function_def(value, name, anchor=node.parent)]
            if value.type == "class":
                return [self.class_def(value, name)]
            wrapped = _wrapped_function(value)
            if wrapped is not None:
                return [
                    self.function_def(
                        wrapped,
                        name,
                        anchor=node.parent,
                        decorators=[self.wrapper(value, wrapped)],
                    )
                ]
        if value is not None and value.type == "call_expression":
            imported = self.require_call(value, name_node)
            if imported is not None:
                return imported
        lowered: m.Expr
        if value is None:
            lowered = m.Literal(line, end, None, origin="undefined")
        else:
            context = (
                _decode(name_node.text) if name_node.type == "identifier" else None
            )
            lowered = self.expr(value, context)
        return [
            m.Assign(
                line,
                end,
                [self.target(name_node)],
                lowered,
                annotation,
                kind,
                origin=node,
            )
        ]

    def wrapper(self, call: Syntax, wrapped: Syntax) -> m.Expr:
        line, end = _span(call)
        arguments = _field(call, "arguments")
        return m.Call(
            line,
            end,
            self.expr(_field(call, "function")),
            [
                self.expr(argument)
                for argument in _named(arguments)
                if argument.id != wrapped.id
            ],
            origin=_field(call, "function"),
        )

    def require_call(self, node: Syntax, binding: Syntax | None) -> list[m.Stmt] | None:
        function = node.child_by_field_name("function")
        if function is None or function.type != "identifier":
            return None
        if _decode(function.text) != "require":
            return None
        arguments = [
            child
            for child in _named(_field(node, "arguments"))
            if child.type == "string"
        ]
        if len(arguments) != 1:
            return []
        self.has_module_syntax = True
        specifier = _string_value(arguments[0])
        line, end = _span(node)
        if binding is None:
            return self.import_of(line, end, specifier, [], node)
        if binding.type == "identifier":
            return self.import_of(
                line, end, specifier, [("*", _decode(binding.text))], node
            )
        if binding.type == "object_pattern":
            return self.import_of(
                line, end, specifier, list(_pattern_names(binding)), node
            )
        return []

    def import_statement(self, node: Syntax) -> list[m.Stmt]:
        source = node.child_by_field_name("source")
        if source is None:
            return []
        specifier = _string_value(source)
        names: list[tuple[str, str]] = []
        clause = next(
            (c for c in node.named_children if c.type == "import_clause"), None
        )
        if clause is not None:
            for part in clause.named_children:
                if part.type == "identifier":
                    names.append(("default", _decode(part.text)))
                elif part.type == "namespace_import":
                    alias = _first(part)
                    if alias is not None:
                        names.append(("*", _decode(alias.text)))
                elif part.type == "named_imports":
                    for specifier_node in part.named_children:
                        if specifier_node.type != "import_specifier":
                            continue
                        imported = _decode(_field(specifier_node, "name").text)
                        alias_node = specifier_node.child_by_field_name("alias")
                        names.append(
                            (
                                imported,
                                _decode(alias_node.text) if alias_node else imported,
                            )
                        )
        line, end = _span(node)
        return self.import_of(line, end, specifier, names, node)

    def import_of(
        self,
        line: int,
        end: int,
        specifier: str,
        names: list[tuple[str, str]],
        node: Syntax,
    ) -> list[m.Stmt]:
        located = self.locate(specifier, self.path)
        if located is None and specifier.startswith("."):
            return []
        target = located if located is not None else _package(specifier)
        whole = [
            alias
            for imported, alias in names
            if imported == "*" or (located is None and imported == "default")
        ]
        named = [
            (imported, alias)
            for imported, alias in names
            if imported != "*" and not (located is None and imported == "default")
        ]
        out: list[m.Stmt] = []
        if whole:
            out.append(
                m.Import(
                    line,
                    end,
                    None,
                    [m.ImportName(line, end, target, alias) for alias in whole],
                    whole=True,
                    origin=node,
                )
            )
        if named or not whole:
            out.append(
                m.Import(
                    line,
                    end,
                    target,
                    [
                        m.ImportName(
                            line, end, imported, None if alias == imported else alias
                        )
                        for imported, alias in named
                    ],
                    origin=node,
                )
            )
        return out

    def export_statement(self, node: Syntax) -> list[m.Stmt]:
        declaration = node.child_by_field_name("declaration")
        is_default = any(child.type == "default" for child in node.children)
        if declaration is not None:
            lowered = self.statement(declaration)
            if is_default:
                for statement in lowered:
                    name = _defined_name(statement)
                    if name is not None and name != "default":
                        self.alias("default", name)
            return lowered
        source = node.child_by_field_name("source")
        clause = next(
            (c for c in node.named_children if c.type == "export_clause"), None
        )
        if source is not None:
            pairs = []
            if clause is not None:
                for specifier in clause.named_children:
                    if specifier.type != "export_specifier":
                        continue
                    exported = _decode(_field(specifier, "name").text)
                    alias = specifier.child_by_field_name("alias")
                    pairs.append((exported, _decode(alias.text) if alias else exported))
            line, end = _span(node)
            module_text = _string_value(source)
            if clause is None:
                namespace = next(
                    (c for c in node.named_children if c.type == "namespace_export"),
                    None,
                )
                alias = _first(namespace) if namespace is not None else None
                if alias is not None:
                    pairs.append(("*", _decode(alias.text)))
                else:
                    located = self.locate(module_text, self.path)
                    if located is None:
                        return []
                    star = m.ImportName(line, end, "*")
                    return [m.Import(line, end, located, [star], origin=node)]
            return self.import_of(line, end, module_text, pairs, node)
        if clause is not None:
            for specifier in clause.named_children:
                if specifier.type != "export_specifier":
                    continue
                exported = _decode(_field(specifier, "name").text)
                alias = specifier.child_by_field_name("alias")
                if alias is not None and _decode(alias.text) != exported:
                    self.alias(_decode(alias.text), exported)
            return []
        value = node.child_by_field_name("value")
        if value is None:
            return []
        value = _unwrap(value)
        if value.type == "identifier":
            self.alias("default", _decode(value.text))
            return []
        if value.type in _FUNCTIONS:
            return [self.function_def(value, "default", anchor=node)]
        if value.type == "class":
            return [self.class_def(value, "default")]
        line, end = _span(node)
        return [
            m.Assign(
                line,
                end,
                [m.Name(line, end, "default", True, origin="default")],
                self.expr(value, "default"),
                None,
                "const",
                origin=node,
            )
        ]

    def alias(self, exported: str, local: str) -> None:
        self.bindings[exported] = ImportBinding(f"{self.name}.{local}", False)

    def if_statement(self, node: Syntax) -> m.If:
        line, end = _span(node)
        alternative = node.child_by_field_name("alternative")
        orelse: list[m.Stmt] = []
        if alternative is not None:
            inner = _first(alternative)
            if inner is not None:
                orelse = (
                    [self.if_statement(inner)]
                    if inner.type == "if_statement"
                    else self.body(inner)
                )
        return m.If(
            line,
            end,
            self.expr(_field(node, "condition")),
            self.body(node.child_by_field_name("consequence")),
            orelse,
            origin=node,
        )

    def for_statement(self, node: Syntax) -> list[m.Stmt]:
        line, end = _span(node)
        out: list[m.Stmt] = []
        initializer = node.child_by_field_name("initializer")
        if initializer is not None:
            if initializer.type in _DECLARATIONS:
                out.extend(self.declaration(initializer))
            elif initializer.type == "expression_statement":
                inner = _first(initializer)
                if inner is not None:
                    out.extend(self.expression_statement(inner))
            elif _is_expression(initializer):
                out.extend(self.expression_statement(initializer))
        condition = node.child_by_field_name("condition")
        if condition is not None and condition.type == "expression_statement":
            condition = _first(condition)
        test: m.Expr = (
            self.expr(condition)
            if condition is not None
            else m.Literal(line, line, True, origin="true")
        )
        body = self.body(node.child_by_field_name("body"))
        increment = node.child_by_field_name("increment")
        if increment is not None:
            body = body + self.expression_statement(increment)
        out.append(m.While(line, end, test, body, origin=node))
        return out

    def for_in(self, node: Syntax) -> m.For:
        line, end = _span(node)
        left = _field(node, "left")
        right = _field(node, "right")
        is_async = any(child.type == "await" for child in node.children)
        return m.For(
            line,
            end,
            self.target(left),
            self.expr(right),
            self.body(node.child_by_field_name("body")),
            is_async=is_async,
            origin=node,
        )

    def try_statement(self, node: Syntax) -> m.Try:
        line, end = _span(node)
        handlers: list[m.Handler] = []
        handler = node.child_by_field_name("handler")
        if handler is not None:
            parameter = handler.child_by_field_name("parameter")
            body = self.body(handler.child_by_field_name("body"))
            name: str | None = None
            if parameter is not None:
                if parameter.type == "identifier":
                    name = _decode(parameter.text)
                else:
                    name = "error"
                    hline, hend = _span(parameter)
                    body = [
                        m.Assign(
                            hline,
                            hend,
                            [self.target(parameter)],
                            m.Name(hline, hend, name, origin=name),
                            origin=parameter,
                        ),
                        *body,
                    ]
            handlers.append(
                m.Handler(*_span(handler), None, name, body, origin=handler)
            )
        finalizer = node.child_by_field_name("finalizer")
        return m.Try(
            line,
            end,
            self.body(node.child_by_field_name("body")),
            handlers,
            [],
            self.body(finalizer.child_by_field_name("body")) if finalizer else [],
            origin=node,
        )

    def switch(self, node: Syntax) -> m.Match:
        line, end = _span(node)
        cases: list[m.Case] = []
        pending: list[m.Expr] = []
        pending_default = False
        first: Syntax | None = None
        body_node = node.child_by_field_name("body")
        for case in _named(body_node) if body_node is not None else []:
            if case.type not in ("switch_case", "switch_default"):
                continue
            first = first or case
            if case.type == "switch_default":
                pending_default = True
            else:
                value = case.child_by_field_name("value")
                if value is not None:
                    pending.append(self.expr(value))
            statements = [
                child
                for child in case.children_by_field_name("body")
                if child.type not in _SKIPPED
            ]
            if not statements:
                continue
            body = self.block(statements)
            while body and isinstance(body[-1], m.Break):
                body.pop()
            cline, cend = _span(first)
            cases.append(
                m.Case(
                    cline,
                    cend,
                    m.Pattern(cline, cend, [], pending_default, pending, origin=first),
                    None,
                    body,
                    origin=case,
                )
            )
            pending, pending_default, first = [], False, None
        if first is not None:
            cline, cend = _span(first)
            cases.append(
                m.Case(
                    cline,
                    cend,
                    m.Pattern(cline, cend, [], pending_default, pending, origin=first),
                    None,
                    [],
                    origin=first,
                )
            )
        return m.Match(line, end, self.expr(_field(node, "value")), cases, origin=node)

    def function_def(
        self,
        node: Syntax,
        name: str,
        *,
        anchor: Syntax | None = None,
        decorators: list[m.Expr] | None = None,
        anonymous: bool = False,
        receiver: str | None = None,
        binding: str = "instance",
        is_property: bool = False,
        is_constructor: bool = False,
    ) -> m.FunctionDef:
        self.scopes[-1].add(name)
        decl = self.function_decl(
            node,
            name,
            anchor=anchor,
            decorators=decorators or [],
            anonymous=anonymous,
            receiver=receiver,
            binding=binding,
            is_property=is_property,
            is_constructor=is_constructor,
        )
        return m.FunctionDef(decl.line, decl.end_line, decl, origin=node)

    def function_decl(
        self,
        node: Syntax,
        name: str,
        *,
        anchor: Syntax | None,
        decorators: list[m.Expr],
        anonymous: bool,
        receiver: str | None,
        binding: str,
        is_property: bool,
        is_constructor: bool,
    ) -> m.FunctionDecl:
        line, end = _span(node)
        outer = anchor if anchor is not None else node
        start = _span(outer)[0]
        decorator_nodes = [c for c in outer.children if c.type == "decorator"]
        decorators = [
            *(self.expr(_first(d) or d) for d in decorator_nodes),
            *decorators,
        ]
        if decorator_nodes:
            start = min(start, _span(decorator_nodes[0])[0])
        doc, doc_lines = _doc_before(_exported(outer))
        self.scopes.append(set())
        self.receivers.append(receiver)
        params, prologue = self.parameters(node.child_by_field_name("parameters"))
        if node.child_by_field_name("parameters") is None:
            single = node.child_by_field_name("parameter")
            if single is not None:
                params = [
                    m.Parameter(*_span(single), _decode(single.text), origin=single)
                ]
        if is_constructor:
            prologue += self.parameter_properties(node)
        body_node = node.child_by_field_name("body")
        expression: m.Expr | None = None
        body: list[m.Stmt]
        if body_node is not None and body_node.type != "statement_block":
            expression = self.expr(body_node)
            bline, bend = _span(body_node)
            body = [m.Return(bline, bend, expression, origin=body_node)]
        else:
            body = self.body(body_node)
        self.scopes.pop()
        self.receivers.pop()
        return m.FunctionDecl(
            line,
            end,
            name,
            [*params],
            self.type_annotation(node.child_by_field_name("return_type")),
            prologue + body,
            decorators,
            _has_token(node, "async"),
            doc,
            doc_lines,
            start,
            binding,
            is_property,
            body_node is None and not is_constructor,
            is_constructor,
            receiver,
            anonymous,
            origin=node,
        )

    def parameters(self, node: Syntax | None) -> tuple[list[m.Parameter], list[m.Stmt]]:
        params: list[m.Parameter] = []
        prologue: list[m.Stmt] = []
        if node is None:
            return params, prologue
        for child in _named(node):
            pattern = child.child_by_field_name("pattern") or child
            if pattern.type == "this":
                continue
            annotation = self.type_annotation(child.child_by_field_name("type"))
            default_node = child.child_by_field_name("value")
            if pattern.type == "assignment_pattern":
                default_node = pattern.child_by_field_name("right")
                pattern = _field(pattern, "left")
            default = self.expr(default_node) if default_node is not None else None
            line, end = _span(child)
            if pattern.type == "rest_pattern":
                inner = _first(pattern)
                name = _decode(inner.text) if inner is not None else "rest"
                params.append(
                    m.Parameter(
                        line, end, name, annotation, None, "variadic", origin=child
                    )
                )
                continue
            if pattern.type in ("object_pattern", "array_pattern"):
                name = _shorten(_collapse(_decode(pattern.text)), 32)
                prologue.append(
                    m.Assign(
                        line,
                        end,
                        [self.target(pattern)],
                        m.Name(line, end, name, origin=name),
                        origin=pattern,
                    )
                )
            else:
                name = _decode(pattern.text)
            params.append(
                m.Parameter(line, end, name, annotation, default, origin=child)
            )
        return params, prologue

    def parameter_properties(self, node: Syntax) -> list[m.Stmt]:
        parameters = node.child_by_field_name("parameters")
        out: list[m.Stmt] = []
        for child in _named(parameters) if parameters is not None else []:
            if not any(
                c.type == "accessibility_modifier" or c.type == "readonly"
                for c in child.children
            ):
                continue
            pattern = child.child_by_field_name("pattern")
            if pattern is None or pattern.type != "identifier":
                continue
            name = _decode(pattern.text)
            line, end = _span(child)
            this = m.Name(line, end, "this", origin="this")
            out.append(
                m.Assign(
                    line,
                    end,
                    [m.Member(line, end, this, name, True, origin=f"this.{name}")],
                    m.Name(line, end, name, origin=name),
                    self.type_annotation(child.child_by_field_name("type")),
                    origin=child,
                )
            )
        return out

    def class_def(self, node: Syntax, name: str) -> m.ClassDef:
        line, end = _span(node)
        self.scopes[-1].add(name)
        bases: list[m.Expr] = []
        for heritage in node.named_children:
            if heritage.type != "class_heritage":
                continue
            for clause in heritage.named_children:
                if clause.type == "extends_clause":
                    bases.extend(
                        self.expr(value)
                        for value in clause.children_by_field_name("value")
                    )
                elif clause.type == "implements_clause":
                    bases.extend(self.type_reference(t) for t in _named(clause))
        decorator_nodes = [c for c in node.children if c.type == "decorator"]
        anchor = _exported(node)
        decorator_nodes += [c for c in anchor.children if c.type == "decorator"]
        start = min([line, *(_span(d)[0] for d in decorator_nodes)])
        doc, doc_lines = _doc_before(anchor)
        body_node = node.child_by_field_name("body")
        self.scopes.append(set())
        body = self.class_body(body_node) if body_node is not None else []
        self.scopes.pop()
        decl = m.ClassDecl(
            line,
            end,
            name,
            bases,
            body,
            [self.expr(_first(d) or d) for d in decorator_nodes],
            doc,
            doc_lines,
            start,
            origin=node,
        )
        return m.ClassDef(line, end, decl, origin=node)

    def class_body(self, node: Syntax) -> list[m.Stmt]:
        out: list[m.Stmt] = []
        for member in _named(node):
            saved = self.hoisted
            self.hoisted = []
            lowered = self.class_member(member)
            out.extend(self.hoisted)
            out.extend(lowered)
            self.hoisted = saved
        return out

    def class_member(self, node: Syntax) -> list[m.Stmt]:
        kind = node.type
        line, end = _span(node)
        if kind in (
            "method_definition",
            "method_signature",
            "abstract_method_signature",
        ):
            name = _member_name(node)
            tokens = _tokens_before_name(node)
            is_static = "static" in tokens
            accessor = "get" if "get" in tokens else "set" if "set" in tokens else None
            return [
                self.function_def(
                    node,
                    name,
                    receiver=None if is_static else "this",
                    binding="static" if is_static else "instance",
                    is_property=accessor == "get",
                    is_constructor=name == "constructor",
                )
            ]
        if kind in (
            "public_field_definition",
            "field_definition",
            "property_signature",
        ):
            name = _member_name(node)
            tokens = _tokens_before_name(node)
            value = node.child_by_field_name("value")
            value = _unwrap(value) if value is not None else None
            is_static = "static" in tokens
            if value is not None and value.type in _FUNCTIONS:
                return [
                    self.function_def(
                        value,
                        name,
                        anchor=node,
                        receiver=None if is_static else "this",
                        binding="static" if is_static else "instance",
                    )
                ]
            annotation = self.type_annotation(node.child_by_field_name("type"))
            if annotation is None and value is not None:
                annotation = _literal_annotation(value)
            if annotation is None:
                annotation = m.TypeOther(line, end, "any", origin=node)
            self.receivers.append(None if is_static else "this")
            lowered = (
                self.expr(value, name)
                if value is not None
                else m.Literal(line, end, None, origin="undefined")
            )
            self.receivers.pop()
            return [
                m.Assign(
                    line,
                    end,
                    [m.Name(line, end, name, True, origin=name)],
                    lowered if value is not None else None,
                    annotation,
                    "static" if is_static else None,
                    origin=node,
                )
            ]
        return []

    def interface(self, node: Syntax) -> m.ClassDef:
        line, end = _span(node)
        name = _name_text(node) or "interface"
        bases: list[m.Expr] = []
        for child in node.named_children:
            if child.type == "extends_type_clause":
                bases.extend(self.type_reference(t) for t in _named(child))
        body_node = node.child_by_field_name("body")
        anchor = _exported(node)
        doc, doc_lines = _doc_before(anchor)
        decl = m.ClassDecl(
            line,
            end,
            name,
            bases,
            self.class_body(body_node) if body_node is not None else [],
            [],
            doc,
            doc_lines,
            _span(anchor)[0],
            "interface",
            origin=node,
        )
        return m.ClassDef(line, end, decl, origin=node)

    def type_alias(self, node: Syntax) -> list[m.Stmt]:
        value = node.child_by_field_name("value")
        if value is None or value.type != "object_type":
            return []
        line, end = _span(node)
        name = _name_text(node) or "type"
        anchor = _exported(node)
        doc, doc_lines = _doc_before(anchor)
        decl = m.ClassDecl(
            line,
            end,
            name,
            [],
            self.class_body(value),
            [],
            doc,
            doc_lines,
            _span(anchor)[0],
            "interface",
            origin=node,
        )
        return [m.ClassDef(line, end, decl, origin=node)]

    def enum(self, node: Syntax) -> m.ClassDef:
        line, end = _span(node)
        name = _name_text(node) or "enum"
        body: list[m.Stmt] = []
        body_node = node.child_by_field_name("body")
        counter = 0
        for member in _named(body_node) if body_node is not None else []:
            mline, mend = _span(member)
            if member.type == "enum_assignment":
                member_name = _member_name(member)
                value_node = member.child_by_field_name("value")
                value = (
                    self.expr(value_node)
                    if value_node is not None
                    else m.Literal(mline, mend, counter, origin=str(counter))
                )
            else:
                member_name = (
                    _string_value(member)
                    if member.type == "string"
                    else _decode(member.text)
                )
                value = m.Literal(mline, mend, counter, origin=str(counter))
            counter += 1
            body.append(
                m.Assign(
                    mline,
                    mend,
                    [m.Name(mline, mend, member_name, True, origin=member_name)],
                    value,
                    origin=member,
                )
            )
        anchor = _exported(node)
        doc, doc_lines = _doc_before(anchor)
        decl = m.ClassDecl(
            line,
            end,
            name,
            [],
            body,
            [],
            doc,
            doc_lines,
            _span(anchor)[0],
            "enum",
            origin=node,
        )
        return m.ClassDef(line, end, decl, origin=node)

    def target(self, node: Syntax) -> m.Expr:
        node = _unwrap(node)
        line, end = _span(node)
        kind = node.type
        if kind in ("identifier", "shorthand_property_identifier_pattern"):
            return m.Name(line, end, _decode(node.text), True, origin=node)
        if kind == "member_expression":
            return m.Member(
                line,
                end,
                self.expr(_field(node, "object")),
                _decode(_field(node, "property").text),
                True,
                origin=node,
            )
        if kind == "subscript_expression":
            return m.Subscript(
                line,
                end,
                self.expr(_field(node, "object")),
                self.expr(_field(node, "index")),
                True,
                origin=node,
            )
        if kind in ("object_pattern", "array_pattern"):
            elements: list[m.Expr] = []
            for child in _named(node):
                elements.append(self.target(_pattern_target(child)))
            return m.Sequence(
                line,
                end,
                "object" if kind == "object_pattern" else "array",
                elements,
                True,
                origin=node,
            )
        if kind == "rest_pattern":
            inner = _first(node)
            return m.Spread(
                line,
                end,
                (
                    self.target(inner)
                    if inner is not None
                    else m.Name(line, end, "rest", True)
                ),
                True,
                origin=node,
            )
        if kind in ("assignment_pattern", "object_assignment_pattern"):
            return self.target(_field(node, "left"))
        if kind in ("lexical_declaration", "variable_declaration"):
            declarator = next(
                (c for c in node.named_children if c.type == "variable_declarator"),
                None,
            )
            if declarator is not None:
                return self.target(_field(declarator, "name"))
        return self.expr(node)

    def expr(self, node: Syntax, context: str | None = None) -> m.Expr:
        node = _unwrap(node)
        line, end = _span(node)
        kind = node.type
        if kind in (
            "identifier",
            "shorthand_property_identifier",
            "property_identifier",
        ):
            text = _decode(node.text)
            if text == "undefined":
                return m.Literal(line, end, None, origin=node)
            return m.Name(line, end, text, origin=node)
        if kind == "this":
            return m.Name(line, end, "this", origin=node)
        if kind == "super":
            return m.Name(line, end, "super", origin=node)
        if kind in ("null", "undefined"):
            return m.Literal(line, end, None, origin=node)
        if kind == "true":
            return m.Literal(line, end, True, origin=node)
        if kind == "false":
            return m.Literal(line, end, False, origin=node)
        if kind == "number":
            return m.Literal(line, end, _number(_decode(node.text)), origin=node)
        if kind == "string":
            return m.Literal(line, end, _string_value(node), origin=node)
        if kind == "template_string":
            return self.template(node)
        if kind == "array":
            return m.Sequence(
                line,
                end,
                "array",
                [self.expr(child, context) for child in _named(node)],
                origin=node,
            )
        if kind == "object":
            return self.object(node, context)
        if kind == "member_expression":
            property_node = _field(node, "property")
            return m.Member(
                line,
                end,
                self.expr(_field(node, "object")),
                _decode(property_node.text),
                origin=node,
            )
        if kind == "subscript_expression":
            return m.Subscript(
                line,
                end,
                self.expr(_field(node, "object")),
                self.expr(_field(node, "index")),
                origin=node,
            )
        if kind == "call_expression":
            return self.call(node)
        if kind == "new_expression":
            constructor = _field(node, "constructor")
            arguments = node.child_by_field_name("arguments")
            return m.Call(
                line,
                end,
                self.expr(constructor),
                (
                    self.arguments(arguments, _callee_name(constructor))
                    if arguments is not None
                    else []
                ),
                construct=True,
                origin=node,
            )
        if kind == "await_expression":
            inner = _first(node)
            return m.Await(
                line,
                end,
                self.expr(inner) if inner is not None else _missing(node),
                origin=node,
            )
        if kind == "yield_expression":
            inner = _first(node)
            return m.Yield(
                line,
                end,
                self.expr(inner) if inner is not None else None,
                _has_token(node, "*"),
                origin=node,
            )
        if kind == "binary_expression":
            return self.binary(node)
        if kind == "unary_expression":
            operator = _operator(node)
            return m.Unary(
                line,
                end,
                _UNARY.get(operator, operator),
                self.expr(_field(node, "argument")),
                origin=node,
            )
        if kind == "ternary_expression":
            return m.Conditional(
                line,
                end,
                self.expr(_field(node, "condition")),
                self.expr(_field(node, "consequence"), context),
                self.expr(_field(node, "alternative"), context),
                origin=node,
            )
        if kind in _FUNCTIONS:
            return self.function_value(node, context)
        if kind == "assignment_expression":
            left = _unwrap(_field(node, "left"))
            value = self.expr(_field(node, "right"), _last_segment(left))
            if left.type == "identifier":
                return m.AssignExpr(
                    line,
                    end,
                    m.Name(*_span(left), _decode(left.text), True, origin=left),
                    value,
                    origin=node,
                )
            return m.OtherExpr(line, end, [self.target(left), value], origin=node)
        if kind in ("augmented_assignment_expression", "update_expression"):
            return m.OtherExpr(
                line,
                end,
                [self.expr(child) for child in _named(node)],
                origin=node,
            )
        if kind == "spread_element":
            inner = _first(node)
            return m.Spread(
                line,
                end,
                self.expr(inner) if inner is not None else _missing(node),
                origin=node,
            )
        if kind in ("jsx_element", "jsx_self_closing_element"):
            return self.jsx(node)
        if kind == "jsx_fragment":
            return m.Call(
                line,
                end,
                m.Name(line, end, "<>", origin="<>"),
                self.jsx_children(node),
                origin=node,
            )
        if kind == "class":
            name = self.unique(context or "class")
            self.hoisted.append(self.class_def(node, name))
            return m.Name(line, end, name, origin=name)
        if kind == "regex":
            return m.OtherExpr(line, end, [], origin=node)
        if kind == "sequence_expression":
            return m.OtherExpr(
                line, end, [self.expr(child) for child in _named(node)], origin=node
            )
        return m.OtherExpr(
            line,
            end,
            [self.expr(child) for child in _named(node) if _is_expression(child)],
            origin=node,
        )

    def template(self, node: Syntax) -> m.Expr:
        line, end = _span(node)
        substitutions = [
            c for c in node.named_children if c.type == "template_substitution"
        ]
        if not substitutions:
            return m.Literal(line, end, _template_text(node), origin=node)
        parts: list[m.Expr] = []
        for child in node.named_children:
            cline, cend = _span(child)
            if child.type == "template_substitution":
                inner = _first(child)
                if inner is not None:
                    parts.append(
                        m.Interpolation(cline, cend, self.expr(inner), origin=child)
                    )
            elif child.type in ("string_fragment", "escape_sequence"):
                parts.append(m.Literal(cline, cend, _fragment(child), origin=child))
        return m.Template(line, end, parts, origin=node)

    def object(self, node: Syntax, context: str | None) -> m.Mapping:
        line, end = _span(node)
        keys: list[m.Expr | None] = []
        values: list[m.Expr] = []
        for child in _named(node):
            cline, cend = _span(child)
            if child.type == "pair":
                key_node = _field(child, "key")
                key = self.key(key_node)
                keys.append(key)
                label = (
                    key.value
                    if isinstance(key, m.Literal) and isinstance(key.value, str)
                    else None
                )
                values.append(
                    self.expr(_field(child, "value"), _member_of(context, label))
                )
            elif child.type == "shorthand_property_identifier":
                text = _decode(child.text)
                keys.append(m.Literal(cline, cend, text, origin=child))
                values.append(m.Name(cline, cend, text, origin=child))
            elif child.type == "spread_element":
                inner = _first(child)
                keys.append(None)
                values.append(
                    self.expr(inner) if inner is not None else _missing(child)
                )
            elif child.type == "method_definition":
                name = _member_name(child)
                keys.append(m.Literal(cline, cend, name, origin=name))
                values.append(
                    self.function_value(child, _member_of(context, name), force=True)
                )
        return m.Mapping(line, end, keys, values, "object", origin=node)

    def key(self, node: Syntax) -> m.Expr:
        line, end = _span(node)
        if node.type in ("property_identifier", "identifier"):
            return m.Literal(line, end, _decode(node.text), origin=node)
        if node.type == "computed_property_name":
            inner = _first(node)
            return self.expr(inner) if inner is not None else _missing(node)
        return self.expr(node)

    def call(self, node: Syntax) -> m.Expr:
        line, end = _span(node)
        function = _field(node, "function")
        arguments = node.child_by_field_name("arguments")
        if arguments is not None and arguments.type == "template_string":
            return m.Call(
                line, end, self.expr(function), [self.template(arguments)], origin=node
            )
        if function.type == "import":
            return m.Call(
                line,
                end,
                m.Name(*_span(function), "import", origin=function),
                self.arguments(arguments, "import"),
                origin=node,
            )
        return m.Call(
            line,
            end,
            self.expr(function),
            self.arguments(arguments, _callee_name(function)),
            origin=node,
        )

    def arguments(self, node: Syntax | None, callee: str) -> list[m.Expr]:
        if node is None:
            return []
        children = _named(node)
        label = next(
            (
                _shorten(_NAME_CHARACTERS.sub(" ", _string_value(child)).strip(), 28)
                for child in children[:1]
                if child.type == "string"
            ),
            "",
        )
        return [
            self.expr(
                child,
                (
                    f"{callee}({label or 'callback'})"
                    if _unwrap(child).type in _FUNCTIONS
                    else f"{callee}({label})"
                ),
            )
            for child in children
        ]

    def binary(self, node: Syntax) -> m.Expr:
        line, end = _span(node)
        operator = _operator(node)
        left = _field(node, "left")
        right = _field(node, "right")
        if operator in _LOGICAL:
            op = _LOGICAL[operator]
            values: list[m.Expr] = []
            for operand in (left, right):
                inner = _unwrap(operand)
                lowered = self.expr(inner)
                if (
                    isinstance(lowered, m.Logical)
                    and lowered.op == op
                    and inner is operand
                ):
                    values.extend(lowered.values)
                else:
                    values.append(lowered)
            return m.Logical(line, end, op, values, origin=node)
        if operator in _COMPARISONS:
            return m.Compare(
                line, end, self.expr(left), [operator], [self.expr(right)], origin=node
            )
        return m.Binary(
            line, end, operator, self.expr(left), self.expr(right), origin=node
        )

    def function_value(
        self, node: Syntax, context: str | None, *, force: bool = False
    ) -> m.Expr:
        line, end = _span(node)
        if not force and _is_expression_arrow(node):
            self.scopes.append(set())
            params, prologue = self.parameters(node.child_by_field_name("parameters"))
            single = node.child_by_field_name("parameter")
            if single is not None:
                params = [
                    m.Parameter(*_span(single), _decode(single.text), origin=single)
                ]
            body = _field(node, "body")
            expression = self.expr(body)
            self.scopes.pop()
            if not prologue:
                return m.Function(
                    line,
                    end,
                    params,
                    [],
                    expression,
                    _has_token(node, "async"),
                    origin=node,
                )
        own = _name_text(node) if node.type != "method_definition" else None
        name = self.unique(own or context or "closure")
        receiver = self.receivers[-1] if node.type == "arrow_function" else None
        self.hoisted.append(
            self.function_def(
                node, name, anonymous=own is None and not force, receiver=receiver
            )
        )
        return m.Name(line, end, name, origin=name)

    def jsx(self, node: Syntax) -> m.Expr:
        line, end = _span(node)
        opening = (
            node
            if node.type == "jsx_self_closing_element"
            else next(
                (c for c in node.named_children if c.type == "jsx_opening_element"),
                node,
            )
        )
        name_node = opening.child_by_field_name("name")
        tag = _decode(name_node.text) if name_node is not None else ""
        if name_node is not None and tag[:1].isupper():
            func = self.expr(name_node)
        else:
            func = m.Name(line, end, f"<{tag}>", origin=f"<{tag}>")
        keywords: list[m.Keyword] = []
        for attribute in opening.children_by_field_name("attribute"):
            aline, aend = _span(attribute)
            if attribute.type == "jsx_expression":
                inner = _first(attribute)
                if inner is not None:
                    keywords.append(
                        m.Keyword(
                            aline,
                            aend,
                            None,
                            self.expr(_first(inner) or inner),
                            origin=attribute,
                        )
                    )
                continue
            if attribute.type != "jsx_attribute":
                continue
            parts = _named(attribute)
            if not parts:
                continue
            attribute_name = _decode(parts[0].text)
            value: m.Expr
            if len(parts) < 2:
                value = m.Literal(aline, aend, True, origin="true")
            elif parts[1].type == "jsx_expression":
                inner = _first(parts[1])
                value = (
                    self.expr(inner, attribute_name)
                    if inner is not None
                    else m.Literal(aline, aend, True, origin="true")
                )
            else:
                value = self.expr(parts[1], attribute_name)
            keywords.append(
                m.Keyword(aline, aend, attribute_name, value, origin=attribute)
            )
        children = self.jsx_children(node) if node.type == "jsx_element" else []
        return m.Call(line, end, func, children, keywords, origin=node)

    def jsx_children(self, node: Syntax) -> list[m.Expr]:
        out: list[m.Expr] = []
        for child in node.named_children:
            line, end = _span(child)
            if child.type in ("jsx_opening_element", "jsx_closing_element"):
                continue
            if child.type == "jsx_text":
                text = _collapse(_decode(child.text))
                if text:
                    out.append(m.Literal(line, end, text, origin=child))
                continue
            if child.type == "jsx_expression":
                inner = _first(child)
                if inner is not None and inner.type not in _SKIPPED:
                    out.append(self.expr(inner))
                continue
            if child.type in (
                "jsx_element",
                "jsx_self_closing_element",
                "jsx_fragment",
            ):
                out.append(self.expr(child))
        return out

    def type_annotation(self, node: Syntax | None) -> m.TypeExpr | None:
        if node is None:
            return None
        if node.type in ("type_annotation", "opting_type_annotation"):
            inner = _first(node)
            return self.type_expr(inner) if inner is not None else None
        return self.type_expr(node)

    def type_reference(self, node: Syntax) -> m.Expr:
        line, end = _span(node)
        if node.type == "generic_type":
            inner = node.child_by_field_name("name")
            if inner is not None:
                return self.type_reference(inner)
        dotted = _decode(node.text)
        parts = dotted.split(".")
        expression: m.Expr = m.Name(line, end, parts[0], origin=parts[0])
        for index, part in enumerate(parts[1:], start=2):
            expression = m.Member(
                line, end, expression, part, origin=".".join(parts[:index])
            )
        return expression

    def type_expr(self, node: Syntax) -> m.TypeExpr:
        line, end = _span(node)
        kind = node.type
        if kind in ("predefined_type", "type_identifier", "nested_type_identifier"):
            return m.TypeName(line, end, _decode(node.text), origin=node)
        if kind == "generic_type":
            name = node.child_by_field_name("name")
            arguments = node.child_by_field_name("type_arguments")
            return m.TypeName(
                line,
                end,
                _decode(name.text) if name is not None else "",
                [self.type_expr(a) for a in _named(arguments)] if arguments else [],
                origin=node,
            )
        if kind == "array_type":
            inner = _first(node)
            return m.TypeName(
                line,
                end,
                "Array",
                [self.type_expr(inner)] if inner is not None else [],
                origin=node,
            )
        if kind == "union_type":
            return m.TypeUnion(
                line,
                end,
                [self.type_expr(member) for member in _union_members(node)],
                origin=node,
            )
        if kind in ("parenthesized_type", "readonly_type", "type_annotation"):
            inner = _first(node)
            return (
                self.type_expr(inner)
                if inner is not None
                else m.TypeOther(line, end, origin=node)
            )
        if kind == "literal_type":
            inner = _first(node)
            if inner is not None and inner.type in ("null", "undefined"):
                return m.TypeName(line, end, inner.type, origin=node)
            value = self.expr(inner) if inner is not None else None
            return m.TypeLiteral(
                line,
                end,
                value.value if isinstance(value, m.Literal) else None,
                origin=node,
            )
        if kind == "function_type":
            return m.TypeOther(line, end, None, "callable", origin=node)
        if kind in ("object_type", "tuple_type"):
            return m.TypeOther(
                line, end, None, "map" if kind == "object_type" else "list", origin=node
            )
        return m.TypeOther(line, end, None, origin=node)

    def unique(self, name: str) -> str:
        taken = self.scopes[-1]
        candidate = name
        counter = 2
        while candidate in taken:
            candidate = f"{name} {counter}"
            counter += 1
        taken.add(candidate)
        return candidate


def _member_of(owner: str | None, key: str | None) -> str | None:
    if key is None:
        return owner
    clean = _NAME_CHARACTERS.sub(" ", key).strip() or "member"
    return f"{owner}.{clean}" if owner else clean


def _exported(node: Syntax) -> Syntax:
    parent = node.parent
    while parent is not None and parent.type in (
        "export_statement",
        "lexical_declaration",
        "variable_declaration",
    ):
        node, parent = parent, parent.parent
    return node


def _named(node: Syntax) -> list[Syntax]:
    return [child for child in node.named_children if child.type not in _SKIPPED]


def _first(node: Syntax) -> Syntax | None:
    return next(iter(_named(node)), None)


def _field(node: Syntax, name: str) -> Syntax:
    child = node.child_by_field_name(name)
    if child is None:
        raise SyntaxError(f"missing {name} in {node.type} at line {_span(node)[0]}")
    return child


def _span(node: Syntax) -> tuple[int, int]:
    return node.start_point[0] + 1, node.end_point[0] + 1


def _decode(data: bytes | None) -> str:
    return data.decode("utf-8", "replace") if data else ""


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _unwrap(node: Syntax) -> Syntax:
    while node.type in (
        "parenthesized_expression",
        "as_expression",
        "satisfies_expression",
        "non_null_expression",
        "type_assertion",
    ):
        inner = next(
            (
                child
                for child in _named(node)
                if child.type not in ("type_arguments",) and _is_expression(child)
            ),
            None,
        )
        if inner is None:
            break
        node = inner
    return node


def _is_expression(node: Syntax) -> bool:
    return not (
        node.type.endswith("_type")
        or node.type
        in (
            "type_annotation",
            "type_arguments",
            "type_parameters",
            "type_identifier",
            "predefined_type",
            "comment",
            "statement_block",
        )
    )


def _missing(node: Syntax) -> m.Expr:
    line, end = _span(node)
    return m.OtherExpr(line, end, [], origin=node)


def _operator(node: Syntax) -> str:
    operator = node.child_by_field_name("operator")
    if operator is not None:
        return _decode(operator.text)
    for child in node.children:
        if not child.is_named:
            return _decode(child.text)
    return ""


def _keyword(node: Syntax) -> str | None:
    for child in node.children:
        if not child.is_named and child.type in ("const", "let", "var", "using"):
            return child.type
    return None


def _has_token(node: Syntax, token: str) -> bool:
    for child in node.children:
        if child.type in ("statement_block", "formal_parameters", "class_body"):
            return False
        if not child.is_named and child.type == token:
            return True
    return False


def _tokens_before_name(node: Syntax) -> set[str]:
    name = node.child_by_field_name("name")
    tokens: set[str] = set()
    for child in node.children:
        if name is not None and child.id == name.id:
            break
        if child.type == "accessibility_modifier":
            tokens.add(_decode(child.text))
        elif not child.is_named:
            tokens.add(child.type)
    return tokens


def _name_text(node: Syntax) -> str | None:
    name = node.child_by_field_name("name")
    return _decode(name.text) if name is not None else None


def _member_name(node: Syntax) -> str:
    name = node.child_by_field_name("name")
    if name is None:
        return "member"
    if name.type == "string":
        return _string_value(name)
    if name.type == "computed_property_name":
        return _collapse(_decode(name.text))
    return _decode(name.text)


def _defined_name(statement: m.Stmt) -> str | None:
    if isinstance(statement, m.FunctionDef):
        return statement.function.name
    if isinstance(statement, m.ClassDef):
        return statement.cls.name
    if isinstance(statement, m.Assign) and len(statement.targets) == 1:
        target = statement.targets[0]
        if isinstance(target, m.Name):
            return target.id
    return None


def _last_segment(node: Syntax) -> str | None:
    node = _unwrap(node)
    if node.type == "identifier":
        return _decode(node.text)
    if node.type == "member_expression":
        return _decode(_field(node, "property").text)
    return None


def _callee_name(node: Syntax) -> str:
    node = _unwrap(node)
    if node.type in ("identifier", "property_identifier"):
        return _decode(node.text)
    if node.type == "member_expression":
        return _decode(_field(node, "property").text)
    if node.type == "call_expression":
        return _callee_name(_field(node, "function"))
    return "call"


def _is_expression_arrow(node: Syntax) -> bool:
    if node.type != "arrow_function":
        return False
    body = node.child_by_field_name("body")
    return body is not None and body.type != "statement_block"


def _wrapped_function(node: Syntax) -> Syntax | None:
    if node.type != "call_expression":
        return None
    function = _unwrap(_field(node, "function"))
    if function.type == "member_expression":
        receiver = _unwrap(_field(function, "object"))
        if receiver.type != "identifier" or not _WRAPPER_RECEIVER.match(
            _decode(receiver.text)
        ):
            return None
    elif function.type != "identifier":
        return None
    arguments = node.child_by_field_name("arguments")
    if arguments is None or arguments.type != "arguments":
        return None
    children = _named(arguments)
    if not children:
        return None
    first = _unwrap(children[0])
    functions = [c for c in children if _unwrap(c).type in _FUNCTIONS]
    if len(functions) != 1 or first.type not in _FUNCTIONS:
        return None
    return first


def _pattern_target(node: Syntax) -> Syntax:
    if node.type == "pair_pattern":
        return _field(node, "value")
    return node


def _pattern_names(node: Syntax) -> Iterator[tuple[str, str]]:
    for child in _named(node):
        if child.type == "shorthand_property_identifier_pattern":
            name = _decode(child.text)
            yield name, name
        elif child.type == "pair_pattern":
            key = _field(child, "key")
            value = _unwrap(_field(child, "value"))
            if value.type == "identifier":
                yield _decode(key.text), _decode(value.text)


def _string_value(node: Syntax) -> str:
    if node.type != "string":
        return _collapse(_decode(node.text))
    return "".join(
        _fragment(child)
        for child in node.named_children
        if child.type in ("string_fragment", "escape_sequence")
    )


def _template_text(node: Syntax) -> str:
    return "".join(
        _fragment(child)
        for child in node.named_children
        if child.type in ("string_fragment", "escape_sequence")
    )


def _fragment(node: Syntax) -> str:
    text = _decode(node.text)
    if node.type != "escape_sequence":
        return text
    try:
        return codecs.decode(text, "unicode_escape")
    except UnicodeDecodeError:
        return text


def _number(text: str) -> int | float:
    cleaned = text.replace("_", "").removesuffix("n")
    try:
        return int(cleaned, 0)
    except ValueError:
        pass
    try:
        return float(cleaned)
    except ValueError:
        return 0


def _package(specifier: str) -> str:
    parts = specifier.split("/")
    head = 2 if specifier.startswith("@") and len(parts) > 1 else 1
    package = "/".join(parts[:head])
    rest = parts[head:]
    return ".".join([package, *rest])


def _union_members(node: Syntax) -> Iterator[Syntax]:
    for child in _named(node):
        if child.type == "union_type":
            yield from _union_members(child)
        else:
            yield child


def _is_data(value: m.Expr | None) -> bool:
    if isinstance(value, (m.Literal, m.Template)):
        return True
    if isinstance(value, m.Sequence):
        return all(_is_data(element) for element in value.elements)
    if isinstance(value, m.Mapping):
        return all(_is_data(item) for item in value.values)
    if isinstance(value, m.Unary):
        return _is_data(value.operand)
    return False


def _literal_annotation(node: Syntax) -> m.TypeExpr | None:
    line, end = _span(node)
    names = {
        "number": "number",
        "string": "string",
        "template_string": "string",
        "true": "boolean",
        "false": "boolean",
    }
    name = names.get(node.type)
    return m.TypeName(line, end, name, origin=name) if name else None


def _error_ratio(root: Syntax) -> float:
    total = max(1, root.end_byte - root.start_byte)
    broken = 0
    pending = [root]
    while pending:
        node = pending.pop()
        if node.type == "ERROR":
            broken += node.end_byte - node.start_byte
            continue
        if node.has_error:
            pending.extend(node.children)
    return broken / total


def _leading_doc(root: Syntax) -> tuple[str | None, tuple[int, int] | None]:
    first = next(iter(root.children), None)
    if first is None or first.type != "comment":
        return None, None
    text = _decode(first.text)
    if not text.startswith("/**"):
        return None, None
    return _doc_text(text), _span(first)


def _doc_before(node: Syntax) -> tuple[str | None, tuple[int, int] | None]:
    previous = node.prev_sibling
    if previous is None or previous.type != "comment":
        return None, None
    text = _decode(previous.text)
    if not text.startswith("/**"):
        return None, None
    if node.start_point[0] - previous.end_point[0] > 1:
        return None, None
    return _doc_text(text), _span(previous)


def _doc_text(text: str) -> str:
    body = text.removeprefix("/**").removesuffix("*/")
    lines = [line.strip().removeprefix("*").strip() for line in body.splitlines()]
    return "\n".join(line for line in lines).strip()
