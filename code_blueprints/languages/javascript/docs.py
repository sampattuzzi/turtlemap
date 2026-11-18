from tree_sitter import Node as Syntax

from code_blueprints.languages.javascript import nodes as ts


def doc_before(node: Syntax) -> tuple[str | None, tuple[int, int] | None]:
    previous = node.prev_sibling
    if previous is None or previous.type != "comment":
        return None, None
    text = ts.decode(previous.text)
    if not text.startswith("/**"):
        return None, None
    if node.start_point[0] - previous.end_point[0] > 1:
        return None, None
    return doc_text(text), ts.span(previous)


def doc_text(text: str) -> str:
    body = text.removeprefix("/**").removesuffix("*/")
    lines = [line.strip().removeprefix("*").strip() for line in body.splitlines()]
    return "\n".join(line for line in lines).strip()
