from tree_sitter import Node as Syntax
from turtlemap.analysis import model as m
from turtlemap.languages.javascript import nodes as ts
from turtlemap.languages.javascript import naming
from turtlemap.languages.javascript import literals
from turtlemap.languages.javascript.lowering.state import LoweringState
from turtlemap.languages.javascript.lowering.ports import (
    ExpressionsPort,
    FunctionsPort,
)


class Composites:
    expressions: ExpressionsPort
    functions: FunctionsPort

    def __init__(self, state: LoweringState) -> None:
        self.state = state

    def template(self, node: Syntax) -> m.Expr:
        line, end = ts.span(node)
        substitutions = [
            c for c in node.named_children if c.type == "template_substitution"
        ]
        if not substitutions:
            return m.Literal(line, end, literals.template_text(node), origin=node)
        parts: list[m.Expr] = []
        for child in node.named_children:
            cline, cend = ts.span(child)
            if child.type == "template_substitution":
                inner = ts.first(child)
                if inner is not None:
                    parts.append(
                        m.Interpolation(
                            cline, cend, self.expressions.expr(inner), origin=child
                        )
                    )
            elif child.type in ("string_fragment", "escape_sequence"):
                parts.append(
                    m.Literal(cline, cend, literals.fragment(child), origin=child)
                )
        return m.Template(line, end, parts, origin=node)

    def object(self, node: Syntax, context: str | None) -> m.Mapping:
        line, end = ts.span(node)
        keys: list[m.Expr | None] = []
        values: list[m.Expr] = []
        for child in ts.named(node):
            cline, cend = ts.span(child)
            if child.type == "pair":
                key_node = ts.field(child, "key")
                key = self.key(key_node)
                keys.append(key)
                label = (
                    key.value
                    if isinstance(key, m.Literal) and isinstance(key.value, str)
                    else None
                )
                values.append(
                    self.expressions.expr(
                        ts.field(child, "value"), naming.member_of(context, label)
                    )
                )
            elif child.type == "shorthand_property_identifier":
                text = ts.decode(child.text)
                keys.append(m.Literal(cline, cend, text, origin=child))
                values.append(m.Name(cline, cend, text, origin=child))
            elif child.type == "spread_element":
                inner = ts.first(child)
                keys.append(None)
                values.append(
                    self.expressions.expr(inner)
                    if inner is not None
                    else ts.missing(child)
                )
            elif child.type == "method_definition":
                name = naming.member_name(child)
                keys.append(m.Literal(cline, cend, name, origin=name))
                values.append(
                    self.functions.function_value(
                        child, naming.member_of(context, name), force=True
                    )
                )
        return m.Mapping(line, end, keys, values, "object", origin=node)

    def key(self, node: Syntax) -> m.Expr:
        line, end = ts.span(node)
        if node.type in ("property_identifier", "identifier"):
            return m.Literal(line, end, ts.decode(node.text), origin=node)
        if node.type == "computed_property_name":
            inner = ts.first(node)
            return (
                self.expressions.expr(inner) if inner is not None else ts.missing(node)
            )
        return self.expressions.expr(node)

    def call(self, node: Syntax) -> m.Expr:
        line, end = ts.span(node)
        function = ts.field(node, "function")
        arguments = node.child_by_field_name("arguments")
        if arguments is not None and arguments.type == "template_string":
            return m.Call(
                line,
                end,
                self.expressions.expr(function),
                [self.template(arguments)],
                origin=node,
            )
        if function.type == "import":
            return m.Call(
                line,
                end,
                m.Name(*ts.span(function), "import", origin=function),
                self.arguments(arguments, "import"),
                origin=node,
            )
        return m.Call(
            line,
            end,
            self.expressions.expr(function),
            self.arguments(arguments, naming.callee_name(function)),
            origin=node,
        )

    def arguments(self, node: Syntax | None, callee: str) -> list[m.Expr]:
        if node is None:
            return []
        children = ts.named(node)
        label = next(
            (
                ts.shorten(
                    naming.NAME_CHARACTERS.sub(
                        " ", literals.string_value(child)
                    ).strip(),
                    28,
                )
                for child in children[:1]
                if child.type == "string"
            ),
            "",
        )
        return [
            self.expressions.expr(
                child,
                (
                    f"{callee}({label or 'callback'})"
                    if ts.unwrap(child).type in ts.FUNCTIONS
                    else f"{callee}({label})"
                ),
            )
            for child in children
        ]
