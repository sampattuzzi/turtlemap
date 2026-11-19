from tree_sitter import Node as Syntax
from turtlemap.analysis import model as m
from turtlemap.languages.javascript import nodes as ts
from turtlemap.languages.javascript import naming
from turtlemap.languages.javascript import docs
from turtlemap.languages.javascript.annotations import TypeAnnotations
from turtlemap.languages.javascript.lowering.state import LoweringState
from turtlemap.languages.javascript.lowering.ports import (
    ExpressionsPort,
    StatementsPort,
    TargetsPort,
)


class Functions:
    expressions: ExpressionsPort
    statements: StatementsPort
    targets: TargetsPort
    types: TypeAnnotations

    def __init__(self, state: LoweringState) -> None:
        self.state = state

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
        self.state.scopes[-1].add(name)
        self.state.declare_name(name)
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
        line, end = ts.span(node)
        outer = anchor if anchor is not None else node
        decorators, start = self._decorators(outer, decorators)
        doc, doc_lines = docs.doc_before(naming.exported(outer))
        self.state.scopes.append(set())
        self.state.receivers.append(receiver)
        self.state.enter_function()
        params, prologue = self._signature(node)
        if is_constructor:
            prologue += self.parameter_properties(node)
        body_node = node.child_by_field_name("body")
        body = self.state.leave_function(params, prologue + self._body(body_node))
        self.state.scopes.pop()
        self.state.receivers.pop()
        return m.FunctionDecl(
            line,
            end,
            name,
            [*params],
            self.types.annotation(node.child_by_field_name("return_type")),
            body,
            decorators,
            ts.has_token(node, "async"),
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

    def _decorators(
        self, outer: Syntax, extra: list[m.Expr]
    ) -> tuple[list[m.Expr], int]:
        start = ts.span(outer)[0]
        found = [c for c in outer.children if c.type == "decorator"]
        lowered = [self.expressions.expr(ts.first(d) or d) for d in found]
        if found:
            start = min(start, ts.span(found[0])[0])
        return [*lowered, *extra], start

    def _signature(self, node: Syntax) -> tuple[list[m.Parameter], list[m.Stmt]]:
        listed = node.child_by_field_name("parameters")
        params, prologue = self.parameters(listed)
        single = node.child_by_field_name("parameter") if listed is None else None
        if single is not None:
            params = [
                m.Parameter(*ts.span(single), ts.decode(single.text), origin=single)
            ]
        return params, prologue

    def _body(self, body_node: Syntax | None) -> list[m.Stmt]:
        if body_node is None or body_node.type == "statement_block":
            return self.statements.body(body_node)
        expression = self.expressions.expr(body_node)
        line, end = ts.span(body_node)
        return [m.Return(line, end, expression, origin=body_node)]

    def parameters(self, node: Syntax | None) -> tuple[list[m.Parameter], list[m.Stmt]]:
        params: list[m.Parameter] = []
        prologue: list[m.Stmt] = []
        if node is None:
            return params, prologue
        for child in ts.named(node):
            pattern = child.child_by_field_name("pattern") or child
            if pattern.type == "this":
                continue
            annotation = self.types.annotation(child.child_by_field_name("type"))
            default_node = child.child_by_field_name("value")
            if pattern.type == "assignment_pattern":
                default_node = pattern.child_by_field_name("right")
                pattern = ts.field(pattern, "left")
            default = (
                self.expressions.expr(default_node)
                if default_node is not None
                else None
            )
            line, end = ts.span(child)
            if pattern.type == "rest_pattern":
                inner = ts.first(pattern)
                name = ts.decode(inner.text) if inner is not None else "rest"
                params.append(
                    m.Parameter(
                        line, end, name, annotation, None, "variadic", origin=child
                    )
                )
                continue
            if pattern.type in ("object_pattern", "array_pattern"):
                name = ts.shorten(ts.collapse(ts.decode(pattern.text)), 32)
                unpacked = self.targets.target(pattern)
                self.state.declare(unpacked)
                prologue.append(
                    m.Assign(
                        line,
                        end,
                        [unpacked],
                        m.Name(line, end, name, origin=name),
                        origin=pattern,
                    )
                )
            else:
                name = ts.decode(pattern.text)
            params.append(
                m.Parameter(line, end, name, annotation, default, origin=child)
            )
        return params, prologue

    def parameter_properties(self, node: Syntax) -> list[m.Stmt]:
        parameters = node.child_by_field_name("parameters")
        out: list[m.Stmt] = []
        for child in ts.named(parameters) if parameters is not None else []:
            if not any(
                c.type == "accessibility_modifier" or c.type == "readonly"
                for c in child.children
            ):
                continue
            pattern = child.child_by_field_name("pattern")
            if pattern is None or pattern.type != "identifier":
                continue
            name = ts.decode(pattern.text)
            line, end = ts.span(child)
            this = m.Name(line, end, "this", origin="this")
            out.append(
                m.Assign(
                    line,
                    end,
                    [m.Member(line, end, this, name, True, origin=f"this.{name}")],
                    m.Name(line, end, name, origin=name),
                    self.types.annotation(child.child_by_field_name("type")),
                    origin=child,
                )
            )
        return out

    def function_value(
        self, node: Syntax, context: str | None, *, force: bool = False
    ) -> m.Expr:
        line, end = ts.span(node)
        if not force and naming.is_expression_arrow(node):
            self.state.scopes.append(set())
            self.state.enter_function()
            params, prologue = self.parameters(node.child_by_field_name("parameters"))
            single = node.child_by_field_name("parameter")
            if single is not None:
                params = [
                    m.Parameter(*ts.span(single), ts.decode(single.text), origin=single)
                ]
            body = ts.field(node, "body")
            expression = self.expressions.expr(body)
            line_of_body = ts.span(body)[0]
            ends: list[m.Stmt] = [m.ExprStmt(line_of_body, line_of_body, expression)]
            markers = self.state.leave_function(params, ends)[: -len(ends)]
            self.state.scopes.pop()
            if not prologue:
                return m.Function(
                    line,
                    end,
                    params,
                    markers,
                    expression,
                    ts.has_token(node, "async"),
                    origin=node,
                )
        own = naming.name_text(node) if node.type != "method_definition" else None
        name = self.expressions.unique(own or context or "closure")
        receiver = self.state.receivers[-1] if node.type == "arrow_function" else None
        self.state.hoisted.append(
            self.function_def(
                node, name, anonymous=own is None and not force, receiver=receiver
            )
        )
        return m.Name(line, end, name, origin=name)
