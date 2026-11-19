from pathlib import Path

from turtlemap.web.collaboration_service import CollaborationService
from turtlemap.review.comments import AGENT, USER, CommentStore
from turtlemap.projects.host import ProjectHost
from turtlemap.web.query_service import QueryService
from turtlemap.projects.seen import SeenStore
from turtlemap.web.comparison_service import ComparisonService
from turtlemap.web.project_service import ProjectService
from turtlemap.web.static_files import StaticFiles
from turtlemap.web.framework import Router, Server

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def start_server(
    host: ProjectHost,
    token: str,
    port: int = 0,
    seen_store: SeenStore | None = None,
    comment_store: CommentStore | None = None,
) -> Server:
    router = make_router(host, seen_store, comment_store)
    server = Server(port, router, {token: USER, host.agent_token: AGENT})
    server.start()
    return server


def make_router(
    host: ProjectHost,
    seen_store: SeenStore | None = None,
    comment_store: CommentStore | None = None,
) -> Router:
    router = Router()
    ProjectService(host).add_routes(router)
    ComparisonService(host, seen_store).add_routes(router)
    CollaborationService(host.root, host.project, comment_store).add_routes(router)
    QueryService(host.project).add_routes(router)
    router.fallback("GET", StaticFiles(STATIC_DIR).serve)
    return router
