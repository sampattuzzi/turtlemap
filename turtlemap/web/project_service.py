from pathlib import Path

from turtlemap.analysis.diff.project_diff import ProjectDiff
from turtlemap.analysis.project import Project
from turtlemap.projects.host import ProjectHost
from turtlemap.projects.recent import recent_projects, remember_project
from turtlemap.web.framework import (
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
