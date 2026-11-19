from tree_sitter import Node as Syntax
from turtlemap.analysis import model as m
from turtlemap.languages.javascript import nodes as ts
from turtlemap.languages.javascript import naming
from turtlemap.languages.javascript import literals
from turtlemap.languages.javascript import docs
from turtlemap.languages.javascript.annotations import TypeAnnotations
from turtlemap.languages.javascript.lowering.state import LoweringState
from turtlemap.languages.javascript.lowering.ports import (
    ExpressionsPort,
    FunctionsPort,
)

_METHODS = frozenset(
    {"method_definition", "method_signature", "abstract_method_signature"}
)

_FIELDS = frozenset(
    {"public_field_definition", "field_definition", "property_signature"}
)


class Classes:
    expressions: ExpressionsPort
    functions: FunctionsPort
    types: TypeAnnotations

    def __init__(self, state: LoweringState) -> None:
        self.state = state

    def class_def(self, node: Syntax, name: str) -> m.ClassDef:
        line, end = ts.span(node)
        self.state.scopes[-1].add(name)
        self.state.declare_name(name)
        bases: list[m.Expr] = []
        for heritage in node.named_children:
            if heritage.type != "class_heritage":
                continue
            for clause in heritage.named_children:
                if clause.type == "extends_clause":
                    bases.extend(
                        self.expressions.expr(value)
                        for value in clause.children_by_field_name("value")
                    )
                elif clause.type == "implements_clause":
                    bases.extend(self.types.reference(t) for t in ts.named(clause))
        decorator_nodes = [c for c in node.children if c.type == "decorator"]
        anchor = naming.exported(node)
        decorator_nodes += [c for c in anchor.children if c.type == "decorator"]
        start = min([line, *(ts.span(d)[0] for d in decorator_nodes)])
        doc, doc_lines = docs.doc_before(anchor)
        body_node = node.child_by_field_name("body")
        self.state.scopes.append(set())
        body = self.class_body(body_node) if body_node is not None else []
        self.state.scopes.pop()
        decl = m.ClassDecl(
            line,
            end,
            name,
            bases,
            body,
            [self.expressions.expr(ts.first(d) or d) for d in decorator_nodes],
            doc,
            doc_lines,
            start,
            origin=node,
        )
        return m.ClassDef(line, end, decl, origin=node)

    def class_body(self, node: Syntax) -> list[m.Stmt]:
        out: list[m.Stmt] = []
        for member in ts.named(node):
            saved = self.state.hoisted
            self.state.hoisted = []
            lowered = self.class_member(member)
            out.extend(self.state.hoisted)
            out.extend(lowered)
            self.state.hoisted = saved
        return out

    def class_member(self, node: Syntax) -> list[m.Stmt]:
        if node.type in _METHODS:
            return [self._method(node)]
        if node.type in _FIELDS:
            return [self._field(node)]
        return []

    def _method(self, node: Syntax) -> m.Stmt:
        name = naming.member_name(node)
        is_static = "static" in naming.tokens_before_name(node)
        return self.functions.function_def(
            node,
            name,
            receiver=_receiver(is_static),
            binding=_binding(is_static),
            is_property="get" in naming.tokens_before_name(node),
            is_constructor=name == "constructor",
        )

    def _field(self, node: Syntax) -> m.Stmt:
        name = naming.member_name(node)
        is_static = "static" in naming.tokens_before_name(node)
        value = node.child_by_field_name("value")
        value = ts.unwrap(value) if value is not None else None
        if value is not None and value.type in ts.FUNCTIONS:
            return self.functions.function_def(
                value,
                name,
                anchor=node,
                receiver=_receiver(is_static),
                binding=_binding(is_static),
            )
        line, end = ts.span(node)
        annotation = self._field_annotation(node, value)
        return m.Assign(
            line,
            end,
            [m.Name(line, end, name, True, origin=name)],
            self._field_value(value, name, is_static),
            annotation,
            "static" if is_static else None,
            origin=node,
        )

    def _field_annotation(self, node: Syntax, value: Syntax | None) -> m.TypeExpr:
        annotation = self.types.annotation(node.child_by_field_name("type"))
        if annotation is None and value is not None:
            annotation = literals.literal_annotation(value)
        if annotation is None:
            return m.TypeOther(*ts.span(node), "any", origin=node)
        return annotation

    def _field_value(
        self, value: Syntax | None, name: str, is_static: bool
    ) -> m.Expr | None:
        if value is None:
            return None
        self.state.receivers.append(_receiver(is_static))
        lowered = self.expressions.expr(value, name)
        self.state.receivers.pop()
        return lowered

    def interface(self, node: Syntax) -> m.ClassDef:
        line, end = ts.span(node)
        name = naming.name_text(node) or "interface"
        bases: list[m.Expr] = []
        for child in node.named_children:
            if child.type == "extends_type_clause":
                bases.extend(self.types.reference(t) for t in ts.named(child))
        body_node = node.child_by_field_name("body")
        anchor = naming.exported(node)
        doc, doc_lines = docs.doc_before(anchor)
        decl = m.ClassDecl(
            line,
            end,
            name,
            bases,
            self.class_body(body_node) if body_node is not None else [],
            [],
            doc,
            doc_lines,
            ts.span(anchor)[0],
            "interface",
            origin=node,
        )
        return m.ClassDef(line, end, decl, origin=node)

    def type_alias(self, node: Syntax) -> list[m.Stmt]:
        value = node.child_by_field_name("value")
        if value is None or value.type != "object_type":
            return []
        line, end = ts.span(node)
        name = naming.name_text(node) or "type"
        anchor = naming.exported(node)
        doc, doc_lines = docs.doc_before(anchor)
        decl = m.ClassDecl(
            line,
            end,
            name,
            [],
            self.class_body(value),
            [],
            doc,
            doc_lines,
            ts.span(anchor)[0],
            "interface",
            origin=node,
        )
        return [m.ClassDef(line, end, decl, origin=node)]

    def enum(self, node: Syntax) -> m.ClassDef:
        line, end = ts.span(node)
        name = naming.name_text(node) or "enum"
        body: list[m.Stmt] = []
        body_node = node.child_by_field_name("body")
        counter = 0
        for member in ts.named(body_node) if body_node is not None else []:
            mline, mend = ts.span(member)
            if member.type == "enum_assignment":
                member_name = naming.member_name(member)
                value_node = member.child_by_field_name("value")
                value = (
                    self.expressions.expr(value_node)
                    if value_node is not None
                    else m.Literal(mline, mend, counter, origin=str(counter))
                )
            else:
                member_name = (
                    literals.string_value(member)
                    if member.type == "string"
                    else ts.decode(member.text)
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
        anchor = naming.exported(node)
        doc, doc_lines = docs.doc_before(anchor)
        decl = m.ClassDecl(
            line,
            end,
            name,
            [],
            body,
            [],
            doc,
            doc_lines,
            ts.span(anchor)[0],
            "enum",
            origin=node,
        )
        return m.ClassDef(line, end, decl, origin=node)


def _receiver(is_static: bool) -> str | None:
    return None if is_static else "this"


def _binding(is_static: bool) -> str:
    return "static" if is_static else "instance"
