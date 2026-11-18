import gzip
import json
import secrets
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, TypeVar
from urllib.parse import parse_qs, urlsplit

JSON = "application/json"
GUEST = "guest"
MAX_BODY = 4_000_000
COMPRESS_ABOVE = 2048


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    role: str
    query: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    content_type: str = JSON
    gzipped: bool = False
    compressible: bool = False


Route = Callable[[Request], Response]
E = TypeVar("E", bound=Exception)


@dataclass(frozen=True)
class ErrorHandler:
    kind: type[Exception]
    respond: Callable[[Any], Response]


def json_response(payload: Any, status: int = 200) -> Response:
    body = json.dumps(payload, separators=(",", ":")).encode()
    return Response(status, body, compressible=True)


def error_response(message: str, status: int) -> Response:
    return json_response({"error": message}, status)


def gzipped_json(data: bytes) -> Response:
    return Response(200, data, gzipped=True)


def not_found(request: Request) -> Response:
    return error_response("Not found", 404)


class Router:
    def __init__(self) -> None:
        self._routes: list[tuple[str, list[str], Route]] = []
        self._fallbacks: dict[str, Route] = {}
        self._error_handlers: list[ErrorHandler] = []

    def get(self, pattern: str, route: Route) -> None:
        self._routes.append(("GET", pattern.split("/"), route))

    def post(self, pattern: str, route: Route) -> None:
        self._routes.append(("POST", pattern.split("/"), route))

    def fallback(self, method: str, route: Route) -> None:
        self._fallbacks[method] = route

    def on_error(self, kind: type[E], respond: Callable[[E], Response]) -> None:
        self._error_handlers.append(ErrorHandler(kind, respond))

    def dispatch(self, request: Request) -> Response:
        route, params = self._find(request)
        try:
            return route(replace(request, params=params))
        except Exception as error:
            for handler in self._error_handlers:
                if isinstance(error, handler.kind):
                    return handler.respond(error)
            raise

    def _find(self, request: Request) -> tuple[Route, dict[str, str]]:
        segments = request.path.split("/")
        for method, pattern, route in self._routes:
            params = _match(pattern, segments)
            if method == request.method and params is not None:
                return route, params
        return self._fallbacks.get(request.method, not_found), {}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, router: Router, roles: dict[str, str]) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.router = router
        self.roles = roles

    def start(self) -> None:
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def role_for(self, token: str) -> str:
        for known, role in self.roles.items():
            if secrets.compare_digest(token, known):
                return role
        return GUEST


class Handler(BaseHTTPRequestHandler):
    server: Server

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        self._respond(self._get)

    def do_POST(self) -> None:
        self._respond(self._post)

    def _get(self) -> Response:
        url = urlsplit(self.path)
        role = self._role()
        if url.path.startswith("/api/") and role == GUEST:
            return error_response("Missing or wrong token", 403)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        return self.server.router.dispatch(Request("GET", url.path, role, query))

    def _post(self) -> Response:
        role = self._role()
        if role == GUEST:
            return error_response("Missing or wrong token", 403)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return error_response("Request too large", 413)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return error_response("Body is not JSON", 400)
        if not isinstance(body, dict):
            return error_response("Body must be a JSON object", 400)
        path = urlsplit(self.path).path
        return self.server.router.dispatch(Request("POST", path, role, body=body))

    def _role(self) -> str:
        return self.server.role_for(self.headers.get("X-Blueprints-Token") or "")

    def _respond(self, answer: Callable[[], Response]) -> None:
        try:
            response = answer()
        except Exception:
            response = error_response(traceback.format_exc(limit=3), 500)
        self._send(self._compressed(response))

    def _compressed(self, response: Response) -> Response:
        accepts_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "")
        large = len(response.body) > COMPRESS_ABOVE
        if not (response.compressible and accepts_gzip and large):
            return response
        return replace(response, body=gzip.compress(response.body, 6), gzipped=True)

    def _send(self, response: Response) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("Cache-Control", "no-store")
        if response.gzipped:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(response.body)


def _match(pattern: list[str], segments: list[str]) -> dict[str, str] | None:
    if len(pattern) != len(segments):
        return None
    params: dict[str, str] = {}
    for wanted, given in zip(pattern, segments):
        if wanted.startswith("{") and wanted.endswith("}"):
            params[wanted[1:-1]] = given
        elif wanted != given:
            return None
    return params
