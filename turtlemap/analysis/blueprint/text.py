from turtlemap.analysis import model as m

LITERAL_LIMIT = 40
LABEL_LIMIT = 40


def shorten(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def unused_name(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    counter = 2
    while f"{name} {counter}" in taken:
        counter += 1
    return f"{name} {counter}"


def pin_name(expression: m.Expr, fallback: str = "value") -> str:
    if isinstance(expression, m.Name):
        return expression.id
    if isinstance(expression, m.Member):
        return expression.attr
    return fallback


def short_name(text: str) -> str:
    return text.rsplit(".", 1)[-1]
