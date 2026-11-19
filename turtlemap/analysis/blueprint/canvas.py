from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from turtlemap.analysis import model as m
from turtlemap.analysis.blueprint.text import shorten, unused_name
from turtlemap.analysis.blueprint.values import Signature, Value
from turtlemap.analysis.types import PinType
from turtlemap.analysis.workspace.parsed import ParsedModule, SymbolRef

MAX_NODES = 250


_TITLE_LIMIT = 60


FRAME_KINDS = frozenset({"closure", "loop", "branch", "lane"})


STRIP_KINDS = frozenset({"closure", "loop", "lane"})


_NOTE_LIMIT = 160


@dataclass
class Pin:
    name: str
    type: PinType
    literal: str | None = None
    cell: bool = False

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "type": self.type.to_json()}
        if self.literal is not None:
            out["lit"] = self.literal
        if self.cell:
            out["cell"] = True
        return out


@dataclass
class GraphNode:
    id: str
    kind: str
    title: str
    line: int
    ins: list[Pin] = field(default_factory=list)
    outs: list[Pin] = field(default_factory=list)
    target: SymbolRef | None = None
    external: str | None = None
    notes: list[str] = field(default_factory=list)
    code: str | None = None
    exec_in: bool = False
    exec_out: bool = False
    exec_outs: list[str] | None = None
    expression: list[str] | None = None
    parent: str | None = None
    reach: str | None = None

    def output(self, name: str) -> Pin | None:
        return next((pin for pin in self.outs if pin.name == name), None)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "line": self.line,
            "ins": [pin.to_json() for pin in self.ins],
            "outs": [pin.to_json() for pin in self.outs],
        }
        if self.target is not None:
            out["target"] = self.target.to_json()
        if self.external is not None:
            out["external"] = self.external
        if self.notes:
            out["note"] = "; ".join(self.notes)
        if self.code:
            out["code"] = self.code
        if self.exec_in:
            out["execIn"] = True
        if self.exec_out:
            out["execOut"] = True
        if self.exec_outs is not None:
            out["execOuts"] = list(self.exec_outs)
        if self.expression is not None:
            out["expr"] = list(self.expression)
        if self.parent is not None:
            out["parent"] = self.parent
        if self.reach is not None:
            out["reach"] = self.reach
        return out


class GraphFull(Exception):
    pass


class Graph:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.nodes: list[GraphNode] = []
        self.edges: list[dict[str, str]] = []
        self.exec: list[dict[str, str]] = []
        self.frame: str | None = None
        self.moment = 0
        self.signatures: dict[str, Signature] = {}
        self._by_id: dict[str, GraphNode] = {}

    def node(self, node_id: str) -> GraphNode:
        return self._by_id[node_id]

    def encloses(self, outer: str | None, inner: str | None) -> bool:
        current = inner
        while current is not None:
            if current == outer:
                return True
            current = self._by_id[current].parent
        return outer is None

    def frame_of(self, value: Value) -> str | None:
        if value.node is None:
            return self.frame
        node = self._by_id[value.node]
        if node.kind in STRIP_KINDS and not (
            node.kind == "closure" and node.outs and node.outs[0].name == value.pin
        ):
            return node.id
        return node.parent

    @contextmanager
    def inside(self, frame: str | None) -> Iterator[None]:
        outer = self.frame
        self.frame = frame
        try:
            yield
        finally:
            self.frame = outer

    def add(
        self,
        kind: str,
        title: str,
        line: int,
        *,
        target: SymbolRef | None = None,
        external: str | None = None,
        note: str | None = None,
        code: str | None = None,
        exec_outs: Sequence[str] | None = None,
    ) -> GraphNode:
        if len(self.nodes) >= self.limit:
            raise GraphFull()
        return self.add_unbounded(
            kind,
            title,
            line,
            target=target,
            external=external,
            note=note,
            code=code,
            exec_outs=exec_outs,
        )

    def add_unbounded(
        self,
        kind: str,
        title: str,
        line: int,
        *,
        target: SymbolRef | None = None,
        external: str | None = None,
        note: str | None = None,
        code: str | None = None,
        exec_outs: Sequence[str] | None = None,
    ) -> GraphNode:
        node = GraphNode(
            f"n{len(self.nodes)}",
            kind,
            shorten(title, _TITLE_LIMIT),
            line,
            target=target,
            external=external,
            exec_outs=_unique_labels(exec_outs) if exec_outs is not None else None,
            parent=self.frame,
        )
        if note:
            node.notes.append(shorten(note, _NOTE_LIMIT))
        if code:
            node.code = shorten(code, _NOTE_LIMIT)
        self.nodes.append(node)
        self._by_id[node.id] = node
        return node

    def connect(
        self,
        node: GraphNode,
        name: str,
        value: Value,
        pin_type: PinType | None = None,
        *,
        cell: bool = False,
    ) -> None:
        unique = unused_name(name, {pin.name for pin in node.ins})
        node.ins.append(
            Pin(
                unique,
                pin_type or value.type,
                value.literal if value.node is None else None,
                cell or value.reference,
            )
        )
        if value.node is not None and value.pin is not None:
            self.edges.append(
                {"from": value.node, "fp": value.pin, "to": node.id, "tp": unique}
            )

    def output(
        self,
        node: GraphNode,
        name: str,
        pin_type: PinType,
        annotation: tuple[m.TypeExpr, ParsedModule] | None = None,
        *,
        cell: bool = False,
    ) -> Value:
        unique = unused_name(name, {pin.name for pin in node.outs})
        node.outs.append(Pin(unique, pin_type, cell=cell))
        return Value(pin_type, node.id, unique, annotation=annotation, reference=cell)

    def link(self, source: GraphNode, label: str, target: GraphNode) -> None:
        if label == "then":
            source.exec_out = True
        elif source.exec_outs is None or label not in source.exec_outs:
            source.exec_outs = [*(source.exec_outs or []), label]
        target.exec_in = True
        self.exec.append({"from": source.id, "fp": label, "to": target.id})
        self.moment += 1

    def strip_exec_when_only_returns(self, head: GraphNode) -> None:
        frame = head.id if head.kind in FRAME_KINDS else None
        members = [node for node in self.nodes if node.parent == frame]
        if any(
            node.kind not in ("entry", "return") and (node.exec_in or node.exec_out)
            for node in members
        ):
            return
        stripped = {head.id, *(node.id for node in members)}
        self.exec[:] = [
            wire
            for wire in self.exec
            if wire["from"] not in stripped or wire["to"] not in stripped
        ]
        head.exec_outs = None
        for node in [head, *members]:
            node.exec_in = False
            node.exec_out = False

    def to_json(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_json() for node in self.nodes],
            "edges": list(self.edges),
            "exec": list(self.exec),
        }


Tail = tuple[GraphNode, str]


class Flow:
    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.tails: list[Tail] = []

    def resume(self, tails: list[Tail]) -> None:
        self.tails = tails

    def step(self, node: GraphNode) -> None:
        for source, label in self.tails:
            self.graph.link(source, label, node)
        self.tails = [(node, "then")]


def _unique_labels(labels: Sequence[str]) -> list[str]:
    unique: list[str] = []
    for label in labels:
        unique.append(unused_name(label, set(unique)))
    return unique
