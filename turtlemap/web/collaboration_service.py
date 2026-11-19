from collections.abc import Callable
from pathlib import Path
from typing import Any

from turtlemap.analysis.project import Project
from turtlemap.review.anchors import locate, source_lines
from turtlemap.review.comments import CommentError, CommentStore
from turtlemap.web.framework import (
    Request,
    Response,
    Router,
    error_response,
    json_response,
)


class CollaborationService:
    def __init__(
        self,
        root: Callable[[], Path | None],
        project: Callable[[], Project | None],
        store: CommentStore | None = None,
    ) -> None:
        self._root = root
        self._project = project
        self.store = store or CommentStore()

    def add_routes(self, router: Router) -> None:
        router.get("/api/comments", self.threads)
        router.get("/api/comments/thread", self.thread)
        router.get("/api/comments/events", self.events)
        router.post("/api/comments", self.create)
        router.post("/api/comments/reply", self.reply)
        router.post("/api/comments/resolve", self.resolve)
        router.post("/api/comments/progress", self.progress)
        router.post("/api/agent/status", self.agent_status)
        router.on_error(CommentError, self.refuse)

    def threads(self, request: Request) -> Response:
        root = self._require_root()
        return json_response(
            {
                "threads": [
                    self._placed(thread) for thread in self.store.threads(root)
                ],
                "cursor": self.store.cursor(root),
                "agent": self.store.agent(root),
            }
        )

    def thread(self, request: Request) -> Response:
        thread = self.store.thread(self._require_root(), request.query.get("id", ""))
        return json_response(self._placed(thread, with_source=True))

    def events(self, request: Request) -> Response:
        since = _number(request.query.get("since"), 0)
        wait = float(_number(request.query.get("wait"), 0))
        answer = self.store.events(self._require_root(), since, wait, request.role)
        answer["threads"] = [self._placed(thread) for thread in answer["threads"]]
        return json_response(answer)

    def create(self, request: Request) -> Response:
        root = self._require_root()
        anchor, body = request.body.get("anchor"), request.body.get("body")
        thread = self.store.create(root, request.role, anchor, body)
        return json_response(self._placed(thread))

    def reply(self, request: Request) -> Response:
        root = self._require_root()
        thread_id, body = _thread_id(request.body), request.body.get("body")
        thread = self.store.reply(root, thread_id, request.role, body)
        return json_response(self._placed(thread))

    def resolve(self, request: Request) -> Response:
        root = self._require_root()
        thread_id = _thread_id(request.body)
        resolved = request.body.get("resolved") is not False
        thread = self.store.resolve(root, thread_id, request.role, resolved)
        return json_response(self._placed(thread))

    def progress(self, request: Request) -> Response:
        root = self._require_root()
        ids = request.body.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise CommentError("Give the comment ids")
        state, note = request.body.get("state"), request.body.get("note")
        threads = self.store.mark(root, ids, request.role, state, note)
        return json_response({"threads": [self._placed(thread) for thread in threads]})

    def agent_status(self, request: Request) -> Response:
        note = request.body.get("note")
        return json_response(
            self.store.set_status(self._require_root(), request.role, note)
        )

    def refuse(self, error: CommentError) -> Response:
        return error_response(str(error), error.status)

    def _require_root(self) -> Path:
        root = self._root()
        if root is None:
            raise CommentError("Open a project first", 409)
        return root

    def _placed(
        self, thread: dict[str, Any], with_source: bool = False
    ) -> dict[str, Any]:
        project = self._project()
        where = locate(thread["anchor"], project)
        if with_source and project is not None:
            for location in where["locations"]:
                if "path" in location and "start" in location:
                    location["source"] = source_lines(
                        project,
                        location["path"],
                        location["start"],
                        location["end"],
                    )
        return {**thread, "where": where}


def _thread_id(body: dict[str, Any]) -> str:
    thread_id = body.get("id")
    if not isinstance(thread_id, str):
        raise CommentError("Give the comment id")
    return thread_id


def _number(text: str | None, default: int) -> int:
    try:
        return int(float(text)) if text is not None else default
    except ValueError:
        return default
