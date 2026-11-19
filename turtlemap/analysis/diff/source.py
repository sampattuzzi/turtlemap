import textwrap

from turtlemap.analysis import model as m
from turtlemap.analysis.project import Project
from turtlemap.analysis.workspace.parsed import ParsedModule


def node_text(module: ParsedModule, node: m.FunctionDecl | m.ClassDecl) -> str:
    start, end = span(node)
    return textwrap.dedent(
        "\n".join(line.rstrip() for line in module.lines[start - 1 : end])
    )


def span(node: m.FunctionDecl | m.ClassDecl) -> tuple[int, int]:
    return node.start_line or node.line, node.end_line or node.line


def function_text(project: Project, path: str, qual: str) -> str | None:
    module = project.workspace.module(path)
    if module is None or qual not in module.functions:
        return None
    return node_text(module, module.functions[qual].node)


def file_source(project: Project, path: str) -> str | None:
    module = project.workspace.module(path)
    if module is not None:
        return module.source
    try:
        return (project.root / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
