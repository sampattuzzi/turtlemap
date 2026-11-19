import hashlib
import textwrap
from dataclasses import dataclass
from typing import Any

from turtlemap.analysis import model as m
from turtlemap.analysis.diff.source import file_source, node_text, span
from turtlemap.analysis.diff.status import ADDED, MODIFIED, REMOVED
from turtlemap.analysis.project import Project
from turtlemap.analysis.workspace.parsed import ParsedModule
from turtlemap.analysis.diff.revisions import FileChange


@dataclass(frozen=True)
class ReviewUnit:
    id: str
    kind: str
    qual: str | None
    owner: str | None
    line: int
    status: str
    fingerprint: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "qual": self.qual,
            "owner": self.owner,
            "line": self.line,
            "diff": self.status,
        }


def review_units(base: Project, head: Project, change: FileChange) -> list[ReviewUnit]:
    path = change.path
    before = (
        _pieces(base, change.old_path or path, path) if change.status != ADDED else {}
    )
    after = _pieces(head, path, path) if change.status != REMOVED else {}
    units = [
        unit
        for unit_id in {**before, **after}
        if (unit := _review_unit(unit_id, before.get(unit_id), after.get(unit_id)))
    ]
    if not units:
        units = [_whole_file_unit(base, head, change)]
    return sorted(units, key=lambda unit: (unit.kind != "top", unit.line))


_Definition = tuple[str, m.FunctionDecl | m.ClassDecl]


@dataclass(frozen=True)
class _Piece:
    kind: str
    qual: str | None
    owner: str | None
    line: int
    text: str


def _whole_file_unit(base: Project, head: Project, change: FileChange) -> ReviewUnit:
    unit_id = f"top:{change.path}"
    before = file_source(base, change.old_path or change.path)
    after = file_source(head, change.path)
    return ReviewUnit(
        unit_id,
        "top",
        None,
        None,
        1,
        change.status,
        _fingerprint(unit_id, f"{change.old_path}\0{before}", after),
    )


def _pieces(project: Project, path: str, unit_path: str) -> dict[str, _Piece]:
    module = project.workspace.module(path)
    if module is None:
        return _unparsed_pieces(project, path, unit_path)
    definitions: list[_Definition] = [
        (qual, parsed.node) for qual, parsed in module.classes.items()
    ] + [(qual, parsed.node) for qual, parsed in module.functions.items()]
    top = _code_outside(
        module.lines, 1, len(module.lines), [span(node) for _, node in definitions]
    )
    return {
        f"top:{unit_path}": _Piece("top", None, None, 1, top),
        **_class_pieces(module, unit_path, definitions),
        **_function_pieces(module, unit_path),
    }


def _unparsed_pieces(project: Project, path: str, unit_path: str) -> dict[str, _Piece]:
    source = file_source(project, path)
    if source is None:
        return {}
    lines = source.splitlines()
    return {
        f"top:{unit_path}": _Piece(
            "top", None, None, 1, _code_outside(lines, 1, len(lines), [])
        )
    }


def _class_pieces(
    module: ParsedModule, unit_path: str, definitions: list[_Definition]
) -> dict[str, _Piece]:
    pieces: dict[str, _Piece] = {}
    for qual, parsed_class in module.classes.items():
        start, end = span(parsed_class.node)
        inner = [
            span(node) for inner, node in definitions if inner.startswith(f"{qual}.")
        ]
        pieces[f"body:{unit_path}:{qual}"] = _Piece(
            "body",
            qual,
            qual,
            start,
            textwrap.dedent(_code_outside(module.lines, start, end, inner)),
        )
    return pieces


def _function_pieces(module: ParsedModule, unit_path: str) -> dict[str, _Piece]:
    pieces: dict[str, _Piece] = {}
    for qual, function in module.functions.items():
        owner = function.class_qualname
        pieces[f"{'m' if owner else 'fn'}:{unit_path}:{qual}"] = _Piece(
            "method" if owner else "function",
            qual,
            owner,
            span(function.node)[0],
            node_text(module, function.node),
        )
    return pieces


def _code_outside(
    lines: list[str], start: int, end: int, holes: list[tuple[int, int]]
) -> str:
    hidden = {number for first, last in holes for number in range(first, last + 1)}
    return "\n".join(
        lines[number - 1].rstrip()
        for number in range(start, end + 1)
        if number not in hidden and lines[number - 1].strip()
    )


def _review_unit(
    unit_id: str, base: _Piece | None, head: _Piece | None
) -> ReviewUnit | None:
    before = base.text if base and base.text else None
    after = head.text if head and head.text else None
    shown = head or base
    if before == after or shown is None:
        return None
    return ReviewUnit(
        unit_id,
        shown.kind,
        shown.qual,
        shown.owner,
        shown.line,
        ADDED if before is None else REMOVED if after is None else MODIFIED,
        _fingerprint(unit_id, before, after),
    )


def _fingerprint(unit_id: str, before: str | None, after: str | None) -> str:
    digest = hashlib.sha256(unit_id.encode())
    for side in (before, after):
        digest.update(b"\0absent" if side is None else b"\0text\0" + side.encode())
    return digest.hexdigest()[:24]
