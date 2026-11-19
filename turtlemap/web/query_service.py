import threading
from collections.abc import Callable
from typing import Any

from turtlemap.analysis.project import Project
from turtlemap.analysis.metrics.code_graph import QueryError
from turtlemap.analysis.structure import Structure
from turtlemap.web.framework import (
    Request,
    Response,
    Router,
    error_response,
    json_response,
)


class QueryService:
    def __init__(self, project: Callable[[], Project | None]) -> None:
        self._project = project
        self._lock = threading.Lock()
        self._built: tuple[Project, dict[str, Any], Structure] | None = None

    def add_routes(self, router: Router) -> None:
        router.get("/api/query/{name}", self.answer)

    def answer(self, request: Request) -> Response:
        name = request.params["name"]
        handler = _HANDLERS.get(name)
        if handler is None:
            choices = ", ".join(sorted(_HANDLERS))
            return error_response(f"No query called {name!r}; try {choices}", 404)
        structure = self.structure()
        if structure is None:
            return error_response("The project is still being read", 409)
        try:
            return json_response(handler(structure, request.query))
        except QueryError as error:
            return error_response(str(error), 400)

    def structure(self) -> Structure | None:
        project = self._project()
        if project is None:
            return None
        overview = project.overview()
        with self._lock:
            if (
                self._built is None
                or self._built[0] is not project
                or self._built[1] is not overview
            ):
                self._built = (project, overview, Structure(overview, project.function))
            return self._built[2]


def _required(query: dict[str, str], key: str) -> str:
    value = query.get(key, "").strip()
    if not value:
        raise QueryError(f"Give {key}=…")
    return value


def _number(query: dict[str, str], key: str, default: int) -> int:
    try:
        return max(1, int(query.get(key, default)))
    except ValueError:
        raise QueryError(f"{key} must be a whole number") from None


_HANDLERS: dict[str, Callable[[Structure, dict[str, str]], dict[str, Any]]] = {
    "report": lambda s, q: s.report(
        q.get("tests") in ("1", "true", "yes"), _number(q, "top", 12)
    ),
    "tree": lambda s, q: s.tree(q.get("name") or None, _number(q, "depth", 2)),
    "find": lambda s, q: s.find(_required(q, "text"), _number(q, "limit", 30)),
    "describe": lambda s, q: s.describe(_required(q, "name")),
    "cohesion": lambda s, q: s.cohesion(_required(q, "name")),
    "coupling": lambda s, q: s.coupling(_required(q, "a"), _required(q, "b")),
    "blueprint": lambda s, q: s.blueprint(_required(q, "name")),
}
