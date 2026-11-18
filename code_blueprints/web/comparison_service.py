from typing import TypeGuard

from code_blueprints.projects.git import GitError, Repository
from code_blueprints.projects.host import ProjectHost
from code_blueprints.projects.seen import SeenStore
from code_blueprints.web.framework import (
    Request,
    Response,
    Router,
    error_response,
    gzipped_json,
    json_response,
)


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


def _seen(unit_ids: list[str]) -> Response:
    return json_response({"seen": unit_ids})


def _no_comparison() -> Response:
    return error_response("No comparison is ready", 409)


def _all_text(values: object) -> TypeGuard[list[str]]:
    return isinstance(values, list) and all(isinstance(value, str) for value in values)
