import json
from collections.abc import Mapping

import tree_sitter_typescript
from tree_sitter import Language as Grammar
from tree_sitter import Node as Syntax
from tree_sitter import Parser

from code_blueprints.analysis import model as m
from code_blueprints.languages.language import (
    Language,
    Locate,
    Lowered,
    stem_parts,
)
from code_blueprints.languages.javascript import nodes as ts
from code_blueprints.languages.javascript import literals
from code_blueprints.languages.javascript import docs
from code_blueprints.languages.javascript.lowering.module import Lowering
from code_blueprints.languages.javascript.profile import (
    JAVASCRIPT_PROFILE,
    JAVASCRIPT_SYNTAX,
)

_TYPESCRIPT = Grammar(tree_sitter_typescript.language_typescript())

_TSX = Grammar(tree_sitter_typescript.language_tsx())

_EXCLUDED_SUFFIXES = (".d.ts", ".d.mts", ".d.cts", ".min.js", ".bundle.js")


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
        lowering = Lowering(self, path, name, locate)
        body = lowering.module(root)
        doc, doc_lines = _leading_doc(root)
        code = m.ModuleCode(
            body=body,
            doc=doc,
            doc_lines=doc_lines,
            is_script=lowering.links.is_script(path, data),
        )
        return Lowered(code, lowering.links.bindings)

    def text(self, node: m.Node) -> str:
        origin = node.origin
        if isinstance(origin, Syntax):
            return ts.collapse(ts.decode(origin.text))
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
            pieces.append(ts.decode(data[cursor - start : span_start - start]))
            pieces.append(name)
            cursor = span_end
        pieces.append(ts.decode(data[cursor - start :]))
        return ts.collapse("".join(pieces))

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
        return bool(bare) and (bare.isupper() or literals.is_data(statement.value))

    def case_label(self, pattern: m.Pattern) -> str:
        if pattern.catch_all:
            return "default"
        return "case " + ", ".join(self.text(value) for value in pattern.references)

    def parse_errors(self) -> tuple[type[Exception], ...]:
        return (SyntaxError, ValueError, RecursionError)


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
    text = ts.decode(first.text)
    if not text.startswith("/**"):
        return None, None
    return docs.doc_text(text), ts.span(first)
