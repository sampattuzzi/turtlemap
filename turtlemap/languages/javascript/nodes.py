from collections.abc import Iterator

from tree_sitter import Node as Syntax

from turtlemap.analysis import model as m

LOGICAL = {"&&": "and", "||": "or", "??": "??"}

UNARY = {"!": "not", "-": "-", "+": "+", "~": "~", "typeof": "typeof", "void": "void"}

FUNCTIONS = frozenset(
    {"arrow_function", "function_expression", "function", "generator_function"}
)

DECLARATIONS = frozenset({"lexical_declaration", "variable_declaration"})

CLASSES = frozenset({"class_declaration", "abstract_class_declaration", "class"})

SKIPPED = frozenset({"comment", "html_comment"})


def named(node: Syntax) -> list[Syntax]:
    return [child for child in node.named_children if child.type not in SKIPPED]


def first(node: Syntax) -> Syntax | None:
    return next(iter(named(node)), None)


def field(node: Syntax, name: str) -> Syntax:
    child = node.child_by_field_name(name)
    if child is None:
        raise SyntaxError(f"missing {name} in {node.type} at line {span(node)[0]}")
    return child


def span(node: Syntax) -> tuple[int, int]:
    return node.start_point[0] + 1, node.end_point[0] + 1


def decode(data: bytes | None) -> str:
    return data.decode("utf-8", "replace") if data else ""


def collapse(text: str) -> str:
    return " ".join(text.split())


def shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def unwrap(node: Syntax) -> Syntax:
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
                for child in named(node)
                if child.type not in ("type_arguments",) and is_expression(child)
            ),
            None,
        )
        if inner is None:
            break
        node = inner
    return node


def is_expression(node: Syntax) -> bool:
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


def missing(node: Syntax) -> m.Expr:
    line, end = span(node)
    return m.OtherExpr(line, end, [], origin=node)


def operator(node: Syntax) -> str:
    operator = node.child_by_field_name("operator")
    if operator is not None:
        return decode(operator.text)
    for child in node.children:
        if not child.is_named:
            return decode(child.text)
    return ""


def keyword(node: Syntax) -> str | None:
    for child in node.children:
        if not child.is_named and child.type in ("const", "let", "var", "using"):
            return child.type
    return None


def has_token(node: Syntax, token: str) -> bool:
    for child in node.children:
        if child.type in ("statement_block", "formal_parameters", "class_body"):
            return False
        if not child.is_named and child.type == token:
            return True
    return False


def pattern_target(node: Syntax) -> Syntax:
    if node.type == "pair_pattern":
        return field(node, "value")
    return node


def pattern_names(node: Syntax) -> Iterator[tuple[str, str]]:
    for child in named(node):
        if child.type == "shorthand_property_identifier_pattern":
            name = decode(child.text)
            yield name, name
        elif child.type == "pair_pattern":
            key = field(child, "key")
            value = unwrap(field(child, "value"))
            if value.type == "identifier":
                yield decode(key.text), decode(value.text)


def union_members(node: Syntax) -> Iterator[Syntax]:
    for child in named(node):
        if child.type == "union_type":
            yield from union_members(child)
        else:
            yield child
