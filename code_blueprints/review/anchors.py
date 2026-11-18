from typing import Any

from code_blueprints.analysis import model as m
from code_blueprints.analysis.project import Project
from code_blueprints.analysis.workspace.parsed import ParsedModule

SNIPPET_LIMIT = 80


def split_id(node_id: str) -> tuple[str, str, str | None]:
    kind, _, rest = node_id.partition(":")
    if kind in ("cls", "fn", "m", "f", "c"):
        path, _, qual = rest.rpartition(":")
        return kind, path, qual
    return kind, rest, None


def locate(anchor: dict[str, Any], project: Project | None) -> dict[str, Any]:
    view = anchor.get("view")
    if project is None:
        return {"locations": [], "outdated": False}
    if view == "map":
        found = [_locate_id(project, str(node_id)) for node_id in anchor.get("ids", [])]
        return {
            "locations": [location for location in found if location is not None],
            "outdated": any(location is None for location in found),
        }
    if view == "blueprint":
        return _locate_blueprint(anchor, project)
    if view == "code":
        return _locate_code(anchor, project)
    return {"locations": [], "outdated": False}


def source_lines(
    project: Project, path: str, start: int, end: int
) -> list[list[Any]] | None:
    module = _module(project, path)
    lines = module.lines if module is not None else _raw_lines(project, path)
    if lines is None:
        return None
    first = max(1, start)
    last = min(len(lines), end, first + SNIPPET_LIMIT - 1)
    return [[number, lines[number - 1]] for number in range(first, last + 1)]


def _locate_id(project: Project, node_id: str) -> dict[str, Any] | None:
    kind, path, qual = split_id(node_id)
    if kind == "pkg":
        return {"id": node_id, "folder": path}
    if kind == "mod":
        module = _module(project, path)
        return (
            {"id": node_id, "path": path, "start": 1, "end": len(module.lines)}
            if module is not None
            else None
        )
    if kind in ("lib", "libmod", "libn"):
        return {"id": node_id, "library": path}
    module = _module(project, path)
    if module is None or qual is None:
        return None
    span = _span(module, kind, qual)
    if span is None:
        return None
    start, end = span
    return {"id": node_id, "path": path, "qual": qual, "start": start, "end": end}


def _span(module: ParsedModule, kind: str, qual: str) -> tuple[int, int] | None:
    node: m.ClassDecl | m.FunctionDecl
    if kind == "cls" and qual in module.classes:
        node = module.classes[qual].node
    elif kind in ("fn", "m") and qual in module.functions:
        node = module.functions[qual].node
    elif kind == "f" and qual.rpartition(".")[0] in module.classes:
        node = module.classes[qual.rpartition(".")[0]].node
    elif kind == "c":
        return _constant_span(module, qual)
    else:
        return None
    return node.start_line or node.line, node.end_line or node.line


def _constant_span(module: ParsedModule, name: str) -> tuple[int, int] | None:
    for statement in module.body:
        targets = statement.targets if isinstance(statement, m.Assign) else []
        if any(isinstance(target, m.Name) and target.id == name for target in targets):
            return statement.line, statement.end_line or statement.line
    return None


def _locate_blueprint(anchor: dict[str, Any], project: Project) -> dict[str, Any]:
    path, qual = str(anchor.get("path", "")), str(anchor.get("qual", ""))
    module = _module(project, path)
    if module is None or qual not in module.functions:
        return {"locations": [], "outdated": True}
    function = module.functions[qual].node
    span = {
        "path": path,
        "qual": qual,
        "start": function.line,
        "end": function.end_line or function.line,
    }
    nodes = [
        {
            "path": path,
            "qual": qual,
            "node": node.get("title"),
            "start": node["line"],
            "end": node["line"],
        }
        for node in anchor.get("nodes", [])
        if isinstance(node, dict) and isinstance(node.get("line"), int)
    ]
    return {"locations": nodes or [span], "function": span, "outdated": False}


def _locate_code(anchor: dict[str, Any], project: Project) -> dict[str, Any]:
    path = str(anchor.get("path", ""))
    start, end = int(anchor.get("start", 1)), int(anchor.get("end", 1))
    module = _module(project, path)
    lines = module.lines if module is not None else _raw_lines(project, path)
    if lines is None:
        return {"locations": [], "outdated": True}
    wanted = [line.rstrip() for line in str(anchor.get("text", "")).split("\n")]
    current = [line.rstrip() for line in lines[start - 1 : end]]
    location = {"path": path, "start": start, "end": end}
    if not any(wanted) or wanted == current:
        return {"locations": [location], "outdated": False}
    moved = _find_block(lines, wanted)
    if moved is not None:
        return {
            "locations": [{**location, "start": moved, "end": moved + len(wanted) - 1}],
            "outdated": False,
            "moved": True,
        }
    return {"locations": [location], "outdated": True}


def _find_block(lines: list[str], wanted: list[str]) -> int | None:
    stripped = [line.rstrip() for line in lines]
    for index in range(len(stripped) - len(wanted) + 1):
        if stripped[index : index + len(wanted)] == wanted:
            return index + 1
    return None


def _module(project: Project, path: str) -> ParsedModule | None:
    if not path or not project.workspace.index.contains(path):
        return None
    return project.workspace.module(path)


def _raw_lines(project: Project, path: str) -> list[str] | None:
    if not path or not project.workspace.index.contains(path):
        return None
    try:
        return (project.root / path).read_text(errors="replace").splitlines()
    except OSError:
        return None
