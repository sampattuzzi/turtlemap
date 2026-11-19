from turtlemap.analysis import model as m


def is_literal_expression(expression: m.Expr | None) -> bool:
    if isinstance(expression, m.Literal):
        return True
    if isinstance(expression, m.Unary) and expression.op in ("-", "+"):
        return isinstance(expression.operand, m.Literal) and isinstance(
            expression.operand.value, (int, float, complex)
        )
    if isinstance(expression, m.Sequence):
        return all(is_literal_expression(element) for element in expression.elements)
    if isinstance(expression, m.Slice):
        return all(
            part is None or is_literal_expression(part)
            for part in (expression.lower, expression.upper, expression.step)
        )
    if isinstance(expression, m.Mapping):
        return all(
            key is not None and is_literal_expression(key) for key in expression.keys
        ) and all(is_literal_expression(value) for value in expression.values)
    return False


def assigned_names(target: m.Expr) -> list[str] | None:
    if isinstance(target, m.Name):
        return [target.id]
    if isinstance(target, m.Spread):
        names = assigned_names(target.value)
        return [f"*{name}" for name in names] if names is not None else None
    if isinstance(target, m.Sequence):
        collected: list[str] = []
        for element in target.elements:
            names = assigned_names(element)
            if names is None:
                return None
            collected.extend(names)
        return collected
    return None


def flat_targets(target: m.Expr) -> list[m.Expr]:
    if isinstance(target, m.Sequence):
        return [leaf for element in target.elements for leaf in flat_targets(element)]
    return [target]
