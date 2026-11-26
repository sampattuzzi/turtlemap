from dataclasses import dataclass, field

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.captures import (
    Closure,
    outer_names,
    shared_and_changing,
)

Compound = m.If | m.For | m.While | m.Match
COMPOUNDS = (m.If, m.For, m.While, m.Match)


@dataclass(frozen=True)
class Variables:
    names: frozenset[str] = frozenset()
    ahead: dict[int, list[str]] = field(default_factory=dict)
    changed_in_place: frozenset[str] = frozenset()

    def declared_ahead_of(self, statement: Compound) -> list[str]:
        return self.ahead.get(id(statement), [])


def find_variables(function: Closure, receivers: frozenset[str]) -> Variables:
    uses = _Uses.of(function)
    outer = outer_names(function) | receivers
    own = m.bound_names(function)
    found = (
        set(shared_and_changing(function)) | uses.mutated_by_closures & uses.assigned()
    ) - outer
    ahead: dict[int, list[str]] = {}
    for compound in uses.compounds:
        stored = uses.stored_in(compound)
        needed = stored & uses.loaded_after(compound)
        if isinstance(compound, (m.For, m.While)):
            outside = uses.bound_outside(compound)
            needed |= stored & uses.loaded_in(compound) & outside
            needed |= (
                (uses.mutated_in(compound) - stored)
                & outside
                & uses.assigned_outside(compound)
            )
        needed -= outer
        found |= needed
        ahead[id(compound)] = [
            name for name in mentioned_names(compound) if name in needed
        ]
    changed_in_place = {use.name for use in uses.uses if use.mutate}
    return Variables(
        frozenset(found),
        ahead,
        frozenset(changed_in_place | uses.mutated_by_closures),
    )


def stored_names(statement: Compound) -> list[str]:
    names: list[str] = []
    for region in _regions(statement):
        found = _region_stores(region)
        if not isinstance(region, m.Expr):
            found += [name for node in _scoped_walk(region) for name in _stores(node)]
        for name in found:
            if name not in names:
                names.append(name)
    return names


def mentioned_names(statement: Compound) -> list[str]:
    names: list[str] = []
    for node in _scoped_walk([statement]):
        for name in _stores(node) or _loads(node):
            if name not in names:
                names.append(name)
    return names


@dataclass
class _Use:
    name: str
    order: int
    store: bool
    mutate: bool
    within: tuple[int, ...]


@dataclass
class _Uses:
    uses: list[_Use] = field(default_factory=list)
    compounds: list[Compound] = field(default_factory=list)
    spans: dict[int, tuple[int, int]] = field(default_factory=dict)
    parameters: frozenset[str] = frozenset()
    mutated_by_closures: set[str] = field(default_factory=set)

    @classmethod
    def of(cls, function: Closure) -> "_Uses":
        uses = cls(parameters=frozenset(p.name for p in function.params))
        for statement in function.body:
            uses._visit(statement, ())
        if isinstance(function, m.Function) and function.expression is not None:
            uses._visit(function.expression, ())
        return uses

    def stored_in(self, compound: Compound) -> set[str]:
        return {use.name for use in self._inside(compound) if use.store}

    def loaded_in(self, compound: Compound) -> set[str]:
        start, end = self.spans[id(compound)]
        return {
            use.name for use in self.uses if not use.store and start <= use.order <= end
        }

    def mutated_in(self, compound: Compound) -> set[str]:
        return {use.name for use in self._inside(compound) if use.mutate}

    def loaded_after(self, compound: Compound) -> set[str]:
        _, end = self.spans[id(compound)]
        return {use.name for use in self.uses if not use.store and use.order > end}

    def assigned(self) -> set[str]:
        return {use.name for use in self.uses if use.store}

    def assigned_outside(self, compound: Compound) -> set[str]:
        return {
            use.name
            for use in self.uses
            if use.store and id(compound) not in use.within
        }

    def bound_outside(self, compound: Compound) -> set[str]:
        return set(self.parameters) | {
            use.name
            for use in self.uses
            if use.store and id(compound) not in use.within
        }

    def _inside(self, compound: Compound) -> list[_Use]:
        return [use for use in self.uses if id(compound) in use.within]

    def _visit(self, node: m.Node, within: tuple[int, ...]) -> None:
        if isinstance(node, COMPOUNDS):
            self._visit_compound(node, within)
            return
        if isinstance(node, (m.FunctionDef, m.ClassDef, m.Function, m.Comprehension)):
            self._visit_nested(node)
            return
        if isinstance(node, m.ExprStmt):
            receiver = _mutated_receiver(node.value)
            if receiver is not None:
                self._add(receiver, within, mutate=True)
        if isinstance(node, (m.Assign, m.AugAssign)):
            targets = node.targets if isinstance(node, m.Assign) else [node.target]
            for target in targets:
                receiver = _stored_container(target)
                if receiver is not None:
                    self._add(receiver, within, mutate=True)
            if isinstance(node, m.AugAssign) and isinstance(node.target, m.Name):
                self._add(node.target.id, within)
        if isinstance(node, m.Name):
            self._add(node.id, within, store=node.store)
            return
        for child in m.children(node):
            self._visit(child, within)

    def _visit_compound(self, node: Compound, within: tuple[int, ...]) -> None:
        self.compounds.append(node)
        start = len(self.uses)
        for header in _headers(node):
            self._visit(header, within)
        inner = (*within, id(node))
        for region in _regions(node):
            for name in _region_stores(region):
                self._add(name, inner, store=True)
            if not isinstance(region, m.Expr):
                for child in region if isinstance(region, list) else [region]:
                    self._visit(child, inner)
        self.spans[id(node)] = (start, len(self.uses) - 1)

    def _visit_nested(self, node: m.Node) -> None:
        local = _nested_locals(node)
        for inner in m.walk(node):
            if isinstance(inner, m.Name) and not inner.store and inner.id not in local:
                self._add(inner.id, ())
            receiver = (
                _mutated_receiver(inner.value)
                if isinstance(inner, m.ExprStmt)
                else None
            )
            if (
                receiver is not None
                and receiver not in local
                and isinstance(node, (m.FunctionDef, m.Function))
            ):
                self.mutated_by_closures.add(receiver)

    def _add(
        self,
        name: str,
        within: tuple[int, ...],
        *,
        store: bool = False,
        mutate: bool = False,
    ) -> None:
        self.uses.append(_Use(name, len(self.uses), store, mutate, within))


def _headers(node: Compound) -> list[m.Expr]:
    if isinstance(node, m.If):
        return [node.test, *_elif_tests(node.orelse)]
    if isinstance(node, m.For):
        return [node.iter]
    if isinstance(node, m.While):
        return [node.test]
    return [node.subject]


def _elif_tests(orelse: list[m.Stmt]) -> list[m.Expr]:
    if len(orelse) == 1 and isinstance(orelse[0], m.If):
        return [orelse[0].test, *_elif_tests(orelse[0].orelse)]
    return []


def _regions(node: Compound) -> list[list[m.Stmt] | m.Node]:
    if isinstance(node, m.If):
        regions: list[list[m.Stmt] | m.Node] = [node.body]
        orelse = node.orelse
        while len(orelse) == 1 and isinstance(orelse[0], m.If):
            regions.append(orelse[0].body)
            orelse = orelse[0].orelse
        if orelse:
            regions.append(orelse)
        return regions
    if isinstance(node, m.For):
        return [node.target, node.body, node.orelse]
    if isinstance(node, m.While):
        return [node.body, node.orelse]
    return [case for case in node.cases]


def _region_stores(region: list[m.Stmt] | m.Node) -> list[str]:
    if isinstance(region, m.Case):
        return list(region.pattern.captures)
    if isinstance(region, m.Expr):
        return [target.id for target in m.walk(region) if isinstance(target, m.Name)]
    return []


def _scoped_walk(region: list[m.Stmt] | m.Node) -> list[m.Node]:
    found: list[m.Node] = []
    pending: list[m.Node] = list(region) if isinstance(region, list) else [region]
    while pending:
        node = pending.pop(0)
        found.append(node)
        if isinstance(node, (m.FunctionDef, m.ClassDef, m.Function, m.Comprehension)):
            continue
        pending.extend(m.children(node))
    return found


def _stores(node: m.Node) -> list[str]:
    if isinstance(node, m.Name) and node.store:
        return [node.id]
    if isinstance(node, m.Case):
        return list(node.pattern.captures)
    return []


def _loads(node: m.Node) -> list[str]:
    return [node.id] if isinstance(node, m.Name) else []


def _mutated_receiver(value: m.Expr) -> str | None:
    if isinstance(value, m.Await):
        value = value.value
    if isinstance(value, m.Call) and isinstance(value.func, m.Member):
        return _root_name(value.func.value)
    return None


def _stored_container(target: m.Expr) -> str | None:
    if isinstance(target, (m.Member, m.Subscript)):
        return _root_name(target.value)
    return None


def _root_name(value: m.Expr) -> str | None:
    while not isinstance(value, m.Name):
        if isinstance(value, m.Call):
            value = value.func
        elif isinstance(value, (m.Member, m.Subscript)):
            value = value.value
        else:
            return None
    return value.id


def _nested_locals(node: m.Node) -> set[str]:
    if isinstance(node, m.Comprehension):
        return set(node.bound)
    if isinstance(node, m.FunctionDef):
        return set(m.bound_names(node.function))
    if isinstance(node, m.Function):
        return set(m.bound_names(node))
    return set()
