from pathlib import Path

from code_blueprints.collaboration import CollaborationService
from code_blueprints.comments import AGENT, USER, CommentStore
from code_blueprints.host import ProjectHost
from code_blueprints.queries import QueryService
from code_blueprints.seen import SeenStore
from code_blueprints.services import ComparisonService, ProjectService, StaticFiles
from code_blueprints.web import Router, Server

STATIC_DIR = Path(__file__).resolve().parent / "static"


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
