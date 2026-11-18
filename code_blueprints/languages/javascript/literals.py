import codecs

from tree_sitter import Node as Syntax

from code_blueprints.analysis import model as m
from code_blueprints.languages.javascript import nodes as ts


def string_value(node: Syntax) -> str:
    if node.type != "string":
        return ts.collapse(ts.decode(node.text))
    return "".join(
        fragment(child)
        for child in node.named_children
        if child.type in ("string_fragment", "escape_sequence")
    )


def template_text(node: Syntax) -> str:
    return "".join(
        fragment(child)
        for child in node.named_children
        if child.type in ("string_fragment", "escape_sequence")
    )


def fragment(node: Syntax) -> str:
    text = ts.decode(node.text)
    if node.type != "escape_sequence":
        return text
    try:
        return codecs.decode(text, "unicode_escape")
    except UnicodeDecodeError:
        return text


def number(text: str) -> int | float:
    cleaned = text.replace("_", "").removesuffix("n")
    try:
        return int(cleaned, 0)
    except ValueError:
        pass
    try:
        return float(cleaned)
    except ValueError:
        return 0


def literal_annotation(node: Syntax) -> m.TypeExpr | None:
    line, end = ts.span(node)
    names = {
        "number": "number",
        "string": "string",
        "template_string": "string",
        "true": "boolean",
        "false": "boolean",
    }
    name = names.get(node.type)
    return m.TypeName(line, end, name, origin=name) if name else None


def is_data(value: m.Expr | None) -> bool:
    if isinstance(value, (m.Literal, m.Template)):
        return True
    if isinstance(value, m.Sequence):
        return all(is_data(element) for element in value.elements)
    if isinstance(value, m.Mapping):
        return all(is_data(item) for item in value.values)
    if isinstance(value, m.Unary):
        return is_data(value.operand)
    return False
