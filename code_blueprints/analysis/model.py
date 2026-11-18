from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field, fields


@dataclass(eq=False)
class Node:
    line: int
    end_line: int
    origin: object = field(default=None, repr=False, kw_only=True)


class Expr(Node):
    pass


class Stmt(Node):
    pass


class TypeExpr(Node):
    pass


@dataclass(eq=False)
class Name(Expr):
    id: str
    store: bool = False


@dataclass(eq=False)
class Member(Expr):
    value: Expr
    attr: str
    store: bool = False


@dataclass(eq=False)
class Keyword(Node):
    arg: str | None
    value: Expr


@dataclass(eq=False)
class Call(Expr):
    func: Expr
    args: list[Expr]
    keywords: list[Keyword] = field(default_factory=list)
    construct: bool = False


@dataclass(eq=False)
class Literal(Expr):
    value: object


@dataclass(eq=False)
class Sequence(Expr):
    kind: str
    elements: list[Expr]
    store: bool = False


@dataclass(eq=False)
class Mapping(Expr):
    keys: list[Expr | None]
    values: list[Expr]
    kind: str = "dict"


@dataclass(eq=False)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(eq=False)
class Unary(Expr):
    op: str
    operand: Expr


@dataclass(eq=False)
class Compare(Expr):
    left: Expr
    ops: list[str]
    comparators: list[Expr]


@dataclass(eq=False)
class Logical(Expr):
    op: str
    values: list[Expr]


@dataclass(eq=False)
class Conditional(Expr):
    test: Expr
    body: Expr
    orelse: Expr


@dataclass(eq=False)
class Subscript(Expr):
    value: Expr
    index: Expr
    store: bool = False


@dataclass(eq=False)
class Slice(Expr):
    lower: Expr | None
    upper: Expr | None
    step: Expr | None


@dataclass(eq=False)
class Interpolation(Expr):
    value: Expr
    spec: Expr | None = None


@dataclass(eq=False)
class Template(Expr):
    parts: list[Expr]


@dataclass(eq=False)
class Comprehension(Expr):
    kind: str
    parts: list[Node]
    bound: list[str]


@dataclass(eq=False)
class Parameter(Node):
    name: str
    annotation: TypeExpr | None = None
    default: Expr | None = None
    kind: str = "positional"


@dataclass(eq=False)
class Function(Expr):
    params: list[Parameter]
    body: list[Stmt]
    expression: Expr | None = None
    is_async: bool = False
    name: str | None = None


@dataclass(eq=False)
class Await(Expr):
    value: Expr


@dataclass(eq=False)
class Yield(Expr):
    value: Expr | None
    delegate: bool = False


@dataclass(eq=False)
class AssignExpr(Expr):
    target: Name
    value: Expr


@dataclass(eq=False)
class Spread(Expr):
    value: Expr
    store: bool = False


@dataclass(eq=False)
class OtherExpr(Expr):
    parts: list[Node] = field(default_factory=list)


@dataclass(eq=False)
class TypeName(TypeExpr):
    dotted: str
    args: list[TypeExpr] = field(default_factory=list)


@dataclass(eq=False)
class TypeUnion(TypeExpr):
    members: list[TypeExpr]


@dataclass(eq=False)
class TypeLiteral(TypeExpr):
    value: object
    parsed: TypeExpr | None = None


@dataclass(eq=False)
class TypeOther(TypeExpr):
    label: str | None = None
    cat: str = "any"
    value: Expr | None = None


@dataclass(eq=False)
class ExprStmt(Stmt):
    value: Expr


@dataclass(eq=False)
class Assign(Stmt):
    targets: list[Expr]
    value: Expr | None
    annotation: TypeExpr | None = None
    declaration: str | None = None


@dataclass(eq=False)
class AugAssign(Stmt):
    target: Expr
    op: str
    value: Expr


@dataclass(eq=False)
class Return(Stmt):
    value: Expr | None


@dataclass(eq=False)
class If(Stmt):
    test: Expr
    body: list[Stmt]
    orelse: list[Stmt]


@dataclass(eq=False)
class For(Stmt):
    target: Expr
    iter: Expr
    body: list[Stmt]
    orelse: list[Stmt] = field(default_factory=list)
    is_async: bool = False


@dataclass(eq=False)
class While(Stmt):
    test: Expr
    body: list[Stmt]
    orelse: list[Stmt] = field(default_factory=list)


@dataclass(eq=False)
class WithItem(Node):
    context: Expr
    target: Expr | None


@dataclass(eq=False)
class With(Stmt):
    items: list[WithItem]
    body: list[Stmt]
    is_async: bool = False


@dataclass(eq=False)
class Handler(Node):
    type: Expr | None
    name: str | None
    body: list[Stmt]


@dataclass(eq=False)
class Try(Stmt):
    body: list[Stmt]
    handlers: list[Handler]
    orelse: list[Stmt] = field(default_factory=list)
    finalbody: list[Stmt] = field(default_factory=list)


@dataclass(eq=False)
class Raise(Stmt):
    exc: Expr | None
    cause: Expr | None = None


@dataclass(eq=False)
class Assert(Stmt):
    test: Expr
    msg: Expr | None = None


@dataclass(eq=False)
class Delete(Stmt):
    targets: list[Expr]


@dataclass(eq=False)
class Break(Stmt):
    pass


@dataclass(eq=False)
class Continue(Stmt):
    pass


@dataclass(eq=False)
class Pass(Stmt):
    pass


@dataclass(eq=False)
class Global(Stmt):
    names: list[str]


@dataclass(eq=False)
class Pattern(Node):
    captures: list[str]
    catch_all: bool
    references: list[Expr] = field(default_factory=list)


@dataclass(eq=False)
class Case(Node):
    pattern: Pattern
    guard: Expr | None
    body: list[Stmt]


@dataclass(eq=False)
class Match(Stmt):
    subject: Expr
    cases: list[Case]


@dataclass(eq=False)
class ImportName(Node):
    name: str
    alias: str | None = None


@dataclass(eq=False)
class Import(Stmt):
    module: str | None
    names: list[ImportName]
    level: int = 0
    whole: bool = False


@dataclass(eq=False)
class OtherStmt(Stmt):
    parts: list[Node] = field(default_factory=list)


@dataclass(eq=False)
class FunctionDecl(Node):
    name: str
    params: list[Parameter]
    returns: TypeExpr | None
    body: list[Stmt]
    decorators: list[Expr] = field(default_factory=list)
    is_async: bool = False
    doc: str | None = None
    doc_lines: tuple[int, int] | None = None
    start_line: int = 0
    binding: str = "instance"
    is_property: bool = False
    is_overload: bool = False
    is_constructor: bool = False
    implicit_receiver: str | None = None
    anonymous: bool = False


@dataclass(eq=False)
class FunctionDef(Stmt):
    function: FunctionDecl


@dataclass(eq=False)
class ClassDecl(Node):
    name: str
    bases: list[Expr]
    body: list[Stmt]
    decorators: list[Expr] = field(default_factory=list)
    doc: str | None = None
    doc_lines: tuple[int, int] | None = None
    start_line: int = 0
    kind: str = "class"


@dataclass(eq=False)
class ClassDef(Stmt):
    cls: ClassDecl


@dataclass(eq=False)
class ModuleCode:
    body: list[Stmt]
    doc: str | None
    doc_lines: tuple[int, int] | None
    is_script: bool = False


def children(node: Node) -> list[Node]:
    if isinstance(node, FunctionDef):
        return children(node.function)
    if isinstance(node, ClassDef):
        return children(node.cls)
    found: list[Node] = []
    for name in _child_fields(type(node)):
        value = getattr(node, name)
        if isinstance(value, Node):
            found.append(value)
        elif isinstance(value, list):
            found.extend(element for element in value if isinstance(element, Node))
    return found


def walk(node: Node) -> Iterator[Node]:
    pending = deque([node])
    while pending:
        current = pending.popleft()
        yield current
        pending.extend(children(current))


def dotted_name(node: Expr) -> str | None:
    if isinstance(node, Name):
        return node.id
    if isinstance(node, Member):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base is not None else None
    return None


def bound_names(definition: FunctionDecl | Function) -> frozenset[str]:
    names = {parameter.name for parameter in definition.params}
    pending: list[Node] = list(definition.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (FunctionDef, ClassDef)):
            names.add(
                node.function.name if isinstance(node, FunctionDef) else node.cls.name
            )
            continue
        if isinstance(node, (Function, Comprehension)):
            continue
        if isinstance(node, Name) and node.store:
            names.add(node.id)
        elif isinstance(node, Handler) and node.name:
            names.add(node.name)
        elif isinstance(node, Pattern):
            names.update(node.captures)
        pending.extend(children(node))
    return frozenset(names)


def decision_points(definition: FunctionDecl) -> int:
    count = 0
    for node in walk(definition):
        if isinstance(
            node, (If, For, While, Handler, Case, Conditional, Comprehension)
        ):
            count += 1
        elif isinstance(node, Logical):
            count += len(node.values) - 1
    return count


_LEAF_TYPES: tuple[object, ...] = (str, bool, int, object, str | None)
_CHILD_FIELDS: dict[type[Node], tuple[str, ...]] = {}


def _child_fields(kind: type[Node]) -> tuple[str, ...]:
    names = _CHILD_FIELDS.get(kind)
    if names is None:
        names = tuple(
            item.name
            for item in fields(kind)
            if item.name != "origin" and item.type not in _LEAF_TYPES
        )
        _CHILD_FIELDS[kind] = names
    return names
