import re

from tree_sitter import Node as Syntax

from code_blueprints.analysis import model as m
from code_blueprints.languages.javascript import nodes as ts
from code_blueprints.languages.javascript import literals

NAME_CHARACTERS = re.compile(r"[.:\s]+")

WRAPPER_RECEIVER = re.compile(r"^[A-Z]")


def member_of(owner: str | None, key: str | None) -> str | None:
    if key is None:
        return owner
    clean = NAME_CHARACTERS.sub(" ", key).strip() or "member"
    return f"{owner}.{clean}" if owner else clean


def exported(node: Syntax) -> Syntax:
    parent = node.parent
    while parent is not None and parent.type in (
        "export_statement",
        "lexical_declaration",
        "variable_declaration",
    ):
        node, parent = parent, parent.parent
    return node


def tokens_before_name(node: Syntax) -> set[str]:
    name = node.child_by_field_name("name")
    tokens: set[str] = set()
    for child in node.children:
        if name is not None and child.id == name.id:
            break
        if child.type == "accessibility_modifier":
            tokens.add(ts.decode(child.text))
        elif not child.is_named:
            tokens.add(child.type)
    return tokens


def name_text(node: Syntax) -> str | None:
    name = node.child_by_field_name("name")
    return ts.decode(name.text) if name is not None else None


def member_name(node: Syntax) -> str:
    name = node.child_by_field_name("name")
    if name is None:
        return "member"
    if name.type == "string":
        return literals.string_value(name)
    if name.type == "computed_property_name":
        return ts.collapse(ts.decode(name.text))
    return ts.decode(name.text)


def defined_name(statement: m.Stmt) -> str | None:
    if isinstance(statement, m.FunctionDef):
        return statement.function.name
    if isinstance(statement, m.ClassDef):
        return statement.cls.name
    if isinstance(statement, m.Assign) and len(statement.targets) == 1:
        target = statement.targets[0]
        if isinstance(target, m.Name):
            return target.id
    return None


def last_segment(node: Syntax) -> str | None:
    node = ts.unwrap(node)
    if node.type == "identifier":
        return ts.decode(node.text)
    if node.type == "member_expression":
        return ts.decode(ts.field(node, "property").text)
    return None


def callee_name(node: Syntax) -> str:
    node = ts.unwrap(node)
    if node.type in ("identifier", "property_identifier"):
        return ts.decode(node.text)
    if node.type == "member_expression":
        return ts.decode(ts.field(node, "property").text)
    if node.type == "call_expression":
        return callee_name(ts.field(node, "function"))
    return "call"


def is_expression_arrow(node: Syntax) -> bool:
    if node.type != "arrow_function":
        return False
    body = node.child_by_field_name("body")
    return body is not None and body.type != "statement_block"


def wrapped_function(node: Syntax) -> Syntax | None:
    if node.type != "call_expression":
        return None
    function = ts.unwrap(ts.field(node, "function"))
    if function.type == "member_expression":
        receiver = ts.unwrap(ts.field(function, "object"))
        if receiver.type != "identifier" or not WRAPPER_RECEIVER.match(
            ts.decode(receiver.text)
        ):
            return None
    elif function.type != "identifier":
        return None
    arguments = node.child_by_field_name("arguments")
    if arguments is None or arguments.type != "arguments":
        return None
    children = ts.named(arguments)
    if not children:
        return None
    first = ts.unwrap(children[0])
    functions = [c for c in children if ts.unwrap(c).type in ts.FUNCTIONS]
    if len(functions) != 1 or first.type not in ts.FUNCTIONS:
        return None
    return first
