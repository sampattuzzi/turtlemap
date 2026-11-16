import gzip
import hashlib
import json
import mimetypes
import os
import secrets
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from code_blueprints.analysis.project import Project

STATIC_DIR = Path(__file__).resolve().parent / "static"
CACHE_VERSION = "1"


def cache_directory() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "code-blueprints"


class ProjectHost:
    def __init__(self, cache_dir: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._project: Project | None = None
        self._overview: dict[str, Any] | None = None
        self._overview_bytes: bytes | None = None
        self._error: str | None = None
        self._loading = False
        self._cache_dir = cache_dir or cache_directory()

    def open(self, root: Path) -> None:
        with self._lock:
            self._project = Project(root)
            self._overview = None
            self._overview_bytes = None
            self._error = None
            self._loading = True
        threading.Thread(target=self._load, args=(self._project,), daemon=True).start()

    def reload(self) -> None:
        with self._lock:
            project = self._project
        if project is not None:
            project.reload()
            self.open(project.root)

    def status(self) -> dict[str, Any]:
        with self._lock:
            project = self._project
            return {
                "open": project is not None,
                "root": str(project.root) if project else None,
                "name": project.root.name if project else None,
                "files": len(project.workspace.files) if project else 0,
                "loading": self._loading,
                "ready": self._overview_bytes is not None,
                "error": self._error,
            }

    def overview_bytes(self) -> bytes | None:
        with self._lock:
            return self._overview_bytes

    def project(self) -> Project | None:
        with self._lock:
            return self._project

    def _load(self, project: Project) -> None:
        try:
            fingerprint = _fingerprint(project)
            cached = self._read_cache(project, fingerprint)
            data = (
                cached
                if cached is not None
                else gzip.compress(
                    json.dumps(project.overview(), separators=(",", ":")).encode(), 6
                )
            )
            if cached is None:
                self._write_cache(project, fingerprint, data)
            with self._lock:
                if self._project is project:
                    self._overview_bytes = data
                    self._loading = False
        except Exception:
            with self._lock:
                if self._project is project:
                    self._error = traceback.format_exc(limit=5)
                    self._loading = False

    def _cache_file(self, project: Project) -> Path:
        key = hashlib.sha1(str(project.root).encode()).hexdigest()[:16]
        return self._cache_dir / f"{key}.json.gz"

    def _read_cache(self, project: Project, fingerprint: str) -> bytes | None:
        try:
            meta = json.loads(
                (self._cache_dir / f"{self._cache_file(project).stem}.meta").read_text()
            )
            if meta.get("fingerprint") != fingerprint:
                return None
            return self._cache_file(project).read_bytes()
        except (OSError, ValueError):
            return None

    def _write_cache(self, project: Project, fingerprint: str, data: bytes) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_file(project).write_bytes(data)
            (self._cache_dir / f"{self._cache_file(project).stem}.meta").write_text(
                json.dumps({"fingerprint": fingerprint, "root": str(project.root)})
            )
        except OSError:
            pass


def _fingerprint(project: Project) -> str:
    digest = hashlib.sha1(CACHE_VERSION.encode())
    for path in project.workspace.files:
        try:
            stat = (project.root / path).stat()
        except OSError:
            continue
        digest.update(f"{path}\0{stat.st_mtime_ns}\0{stat.st_size}\n".encode())
    return digest.hexdigest()


def make_handler(host: ProjectHost, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                self._route(url.path, query)
            except Exception:
                self._json({"error": traceback.format_exc(limit=3)}, 500)

        def _route(self, path: str, query: dict[str, str]) -> None:
            if path.startswith("/api/") and not secrets.compare_digest(
                self.headers.get("X-Blueprints-Token") or "", token
            ):
                self._json({"error": "Missing or wrong token"}, 403)
            elif path == "/api/status":
                self._json(host.status())
            elif path == "/api/project":
                data = host.overview_bytes()
                if data is None:
                    self._json({"error": "Project is still loading"}, 409)
                else:
                    self._send(200, data, "application/json", gzipped=True)
            elif path == "/api/function":
                project = host.project()
                result = (
                    project.function(query.get("path", ""), query.get("qual", ""))
                    if project
                    else None
                )
                if result is None:
                    self._json({"error": "No such function"}, 404)
                else:
                    self._json(result)
            elif path == "/api/outline":
                project = host.project()
                outline = project.outline(query.get("path", "")) if project else None
                if outline is None:
                    self._json({"error": "No such module"}, 404)
                else:
                    self._json(outline)
            elif path == "/api/open":
                self._open(query.get("root"))
            elif path == "/api/reload":
                host.reload()
                self._json(host.status())
            elif path == "/api/capabilities":
                self._json({"recent": recent_projects()})
            else:
                self._static(path)

        def _open(self, root: str | None) -> None:
            if not root:
                self._json({"error": "No folder chosen"}, 400)
                return
            folder = Path(root).expanduser()
            if not folder.is_dir():
                self._json({"error": f"Not a folder: {folder}"}, 400)
                return
            host.open(folder)
            remember_project(folder)
            self._json(host.status())

        def _static(self, path: str) -> None:
            relative = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (STATIC_DIR / relative).resolve()
            if STATIC_DIR not in target.parents or not target.is_file():
                self._json({"error": "Not found"}, 404)
                return
            content_type = (
                mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            )
            self._send(200, target.read_bytes(), content_type)

        def _json(self, payload: Any, status: int = 200) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            if len(body) > 2048 and "gzip" in (
                self.headers.get("Accept-Encoding") or ""
            ):
                self._send(
                    status, gzip.compress(body, 6), "application/json", gzipped=True
                )
            else:
                self._send(status, body, "application/json")

        def _send(
            self, status: int, body: bytes, content_type: str, gzipped: bool = False
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if gzipped:
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def start_server(host: ProjectHost, token: str, port: int = 0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(host, token))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def config_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "code-blueprints" / "recent.json"


def recent_projects() -> list[str]:
    try:
        entries = json.loads(config_file().read_text())
    except (OSError, ValueError):
        return []
    return [
        entry for entry in entries if isinstance(entry, str) and Path(entry).is_dir()
    ][:8]


def remember_project(folder: Path) -> None:
    entries = [str(folder.resolve())] + [
        entry for entry in recent_projects() if entry != str(folder.resolve())
    ]
    try:
        config_file().parent.mkdir(parents=True, exist_ok=True)
        config_file().write_text(json.dumps(entries[:8]))
    except OSError:
        pass
