from tree_sitter import Node as Syntax
from turtlemap.analysis import model as m
from turtlemap.languages.javascript import nodes as ts
from turtlemap.languages.javascript.lowering.state import LoweringState
from turtlemap.languages.javascript.lowering.ports import ExpressionsPort


class Jsx:
    expressions: ExpressionsPort

    def __init__(self, state: LoweringState) -> None:
        self.state = state

    def jsx(self, node: Syntax) -> m.Expr:
        line, end = ts.span(node)
        opening = _opening(node)
        name_node = opening.child_by_field_name("name")
        tag = ts.decode(name_node.text) if name_node is not None else ""
        if name_node is not None and tag[:1].isupper():
            func = self.expressions.expr(name_node)
        else:
            func = m.Name(line, end, f"<{tag}>", origin=f"<{tag}>")
        keywords = [
            keyword
            for attribute in opening.children_by_field_name("attribute")
            if (keyword := self._attribute(attribute)) is not None
        ]
        children = self.jsx_children(node) if node.type == "jsx_element" else []
        return m.Call(line, end, func, children, keywords, origin=node)

    def _attribute(self, attribute: Syntax) -> m.Keyword | None:
        line, end = ts.span(attribute)
        if attribute.type == "jsx_expression":
            inner = ts.first(attribute)
            if inner is None:
                return None
            spread = self.expressions.expr(ts.first(inner) or inner)
            return m.Keyword(line, end, None, spread, origin=attribute)
        parts = ts.named(attribute) if attribute.type == "jsx_attribute" else []
        if not parts:
            return None
        name = ts.decode(parts[0].text)
        value = self._attribute_value(parts, name, line, end)
        return m.Keyword(line, end, name, value, origin=attribute)

    def _attribute_value(
        self, parts: list[Syntax], name: str, line: int, end: int
    ) -> m.Expr:
        if len(parts) < 2:
            return m.Literal(line, end, True, origin="true")
        if parts[1].type != "jsx_expression":
            return self.expressions.expr(parts[1], name)
        inner = ts.first(parts[1])
        if inner is None:
            return m.Literal(line, end, True, origin="true")
        return self.expressions.expr(inner, name)

    def jsx_children(self, node: Syntax) -> list[m.Expr]:
        out: list[m.Expr] = []
        for child in node.named_children:
            line, end = ts.span(child)
            if child.type in ("jsx_opening_element", "jsx_closing_element"):
                continue
            if child.type == "jsx_text":
                text = ts.collapse(ts.decode(child.text))
                if text:
                    out.append(m.Literal(line, end, text, origin=child))
                continue
            if child.type == "jsx_expression":
                inner = ts.first(child)
                if inner is not None and inner.type not in ts.SKIPPED:
                    out.append(self.expressions.expr(inner))
                continue
            if child.type in (
                "jsx_element",
                "jsx_self_closing_element",
                "jsx_fragment",
            ):
                out.append(self.expressions.expr(child))
        return out


def _opening(node: Syntax) -> Syntax:
    if node.type == "jsx_self_closing_element":
        return node
    return next(
        (c for c in node.named_children if c.type == "jsx_opening_element"), node
    )
