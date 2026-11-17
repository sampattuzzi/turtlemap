import mimetypes
from pathlib import Path
from typing import TypeGuard

from code_blueprints.analysis.diff import ProjectDiff
from code_blueprints.analysis.project import Project
from code_blueprints.git import GitError, Repository
from code_blueprints.host import ProjectHost
from code_blueprints.recent import recent_projects, remember_project
from code_blueprints.seen import SeenStore
from code_blueprints.web import (
    Request,
    Response,
    Router,
    error_response,
    gzipped_json,
    json_response,
)


class ProjectService:
    def __init__(self, host: ProjectHost) -> None:
        self._host = host

    def add_routes(self, router: Router) -> None:
        router.get("/api/status", self.status)
        router.get("/api/open", self.open)
        router.get("/api/reload", self.reload)
        router.get("/api/project", self.overview)
        router.get("/api/function", self.function)
        router.get("/api/outline", self.outline)
        router.get("/api/capabilities", self.capabilities)

    def status(self, request: Request) -> Response:
        return json_response(self._host.status())

    def open(self, request: Request) -> Response:
        root = request.query.get("root")
        if not root:
            return error_response("No folder chosen", 400)
        folder = Path(root).expanduser()
        if not folder.is_dir():
            return error_response(f"Not a folder: {folder}", 400)
        self._host.open(folder)
        remember_project(folder)
        return json_response(self._host.status())

    def reload(self, request: Request) -> Response:
        self._host.reload()
        return json_response(self._host.status())

    def overview(self, request: Request) -> Response:
        data = self._host.session().overview_bytes
        if data is None:
            return error_response("Project is still loading", 409)
        return gzipped_json(data)

    def function(self, request: Request) -> Response:
        source = self._shown()
        path, qual = request.query.get("path", ""), request.query.get("qual", "")
        result = source.function(path, qual) if source else None
        if result is None:
            return error_response("No such function", 404)
        return json_response(result)

    def outline(self, request: Request) -> Response:
        source = self._shown()
        outline = source.outline(request.query.get("path", "")) if source else None
        if outline is None:
            return error_response("No such module", 404)
        return json_response(outline)

    def capabilities(self, request: Request) -> Response:
        return json_response({"recent": recent_projects()})

    def _shown(self) -> ProjectDiff | Project | None:
        session = self._host.session()
        return session.diff or session.project


class ComparisonService:
    def __init__(self, host: ProjectHost, seen_store: SeenStore | None = None) -> None:
        self._host = host
        self._seen_store = seen_store or SeenStore()

    def add_routes(self, router: Router) -> None:
        router.get("/api/diff", self.compare)
        router.get("/api/diff/data", self.data)
        router.get("/api/branches", self.branches)
        router.get("/api/seen", self.seen)
        router.post("/api/seen", self.mark_seen)

    def compare(self, request: Request) -> Response:
        spec = (request.query.get("spec") or "").strip()
        try:
            if spec:
                self._host.open_diff(spec)
            else:
                self._host.clear_diff()
        except GitError as error:
            return error_response(str(error), 400)
        return json_response(self._host.status())

    def data(self, request: Request) -> Response:
        data = self._host.session().diff_bytes
        if data is None:
            return error_response("No comparison is ready", 409)
        return gzipped_json(data)

    def branches(self, request: Request) -> Response:
        root = self._host.root()
        try:
            names = Repository(root).branches() if root else []
        except GitError:
            names = []
        return json_response({"branches": names})

    def seen(self, request: Request) -> Response:
        session = self._host.session()
        root, diff = session.root, session.diff
        if root is None or diff is None:
            return _no_comparison()
        return _seen(diff.seen_units(self._seen_store.load(root)))

    def mark_seen(self, request: Request) -> Response:
        unit_ids = request.body.get("ids")
        if not _all_text(unit_ids):
            return error_response("Give the ids to mark", 400)
        session = self._host.session()
        root, diff = session.root, session.diff
        if root is None or diff is None:
            return _no_comparison()
        fingerprints = diff.fingerprints(unit_ids)
        if request.body.get("seen") is False:
            stored = self._seen_store.update(root, [], fingerprints)
        else:
            stored = self._seen_store.update(root, fingerprints, [])
        return _seen(diff.seen_units(stored))


class StaticFiles:
    def __init__(self, folder: Path) -> None:
        self._folder = folder.resolve()

    def serve(self, request: Request) -> Response:
        relative = request.path.lstrip("/") or "index.html"
        target = (self._folder / relative).resolve()
        if self._folder not in target.parents or not target.is_file():
            return error_response("Not found", 404)
        content_type = mimetypes.guess_type(target.name)[0]
        return Response(
            200, target.read_bytes(), content_type or "application/octet-stream"
        )


def _seen(unit_ids: list[str]) -> Response:
    return json_response({"seen": unit_ids})


def _no_comparison() -> Response:
    return error_response("No comparison is ready", 409)


def _all_text(values: object) -> TypeGuard[list[str]]:
    return isinstance(values, list) and all(isinstance(value, str) for value in values)
