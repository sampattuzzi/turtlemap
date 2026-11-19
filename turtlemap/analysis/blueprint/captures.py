from collections import Counter

from turtlemap.analysis import model as m

Closure = m.Function | m.FunctionDecl


def shared_and_changing(function: Closure) -> frozenset[str]:
    own = own_names(function)
    captured: set[str] = set()
    for closure in _closures_in(function.body):
        captured.update(_free_names(closure))
    if isinstance(function, m.Function) and function.expression is not None:
        for closure in _closures_in([function.expression]):
            captured.update(_free_names(closure))
    stores = _store_counts(function)
    return frozenset(name for name in own & captured if stores[name] > 1)


def own_names(function: Closure) -> frozenset[str]:
    parameters = {parameter.name for parameter in function.params}
    return frozenset(m.bound_names(function) - outer_names(function) - parameters)


def outer_names(function: Closure) -> frozenset[str]:
    return frozenset(
        name
        for statement in function.body
        if isinstance(statement, m.Global)
        for name in statement.names
    )


def reassigned_globals(module_body: list[m.Stmt]) -> frozenset[str]:
    return frozenset(
        name
        for statement in module_body
        for node in m.walk(statement)
        if isinstance(node, m.Global)
        for name in node.names
    )


def _closures_in(nodes: list[m.Stmt] | list[m.Expr]) -> list[Closure]:
    found: list[Closure] = []
    for root in nodes:
        for node in m.walk(root):
            if isinstance(node, m.Function):
                found.append(node)
            elif isinstance(node, m.FunctionDef):
                found.append(node.function)
    return found


def _free_names(closure: Closure) -> set[str]:
    local = own_names(closure) | {parameter.name for parameter in closure.params}
    return {
        node.id
        for node in m.walk(closure)
        if isinstance(node, m.Name) and node.id not in local
    }


def _store_counts(function: Closure) -> Counter[str]:
    counts: Counter[str] = Counter()
    for statement in function.body:
        for node in m.walk(statement):
            if isinstance(node, m.Name) and node.store:
                counts[node.id] += 1
            elif isinstance(node, m.For):
                for target in m.walk(node.target):
                    if isinstance(target, m.Name):
                        counts[target.id] += 1
    if isinstance(function, m.Function) and function.expression is not None:
        for node in m.walk(function.expression):
            if isinstance(node, m.Name) and node.store:
                counts[node.id] += 1
    return counts
