import gzip
import json
import time
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path
from textwrap import dedent
from typing import Any, Callable, Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from code_blueprints.analysis.project import Project
from code_blueprints.review.comments import CommentStore
from code_blueprints.projects.seen import SeenStore
from code_blueprints.projects.host import ProjectHost
from code_blueprints.web.server import start_server

TOKEN = "user-token"
SOURCE = "class Square:\n    def area(self, side: float) -> float:\n        return side * side\n"

ProjectFactory = Callable[[dict[str, str]], Project]


@pytest.fixture
def make_project(tmp_path: Path) -> ProjectFactory:
    def make(files: dict[str, str]) -> Project:
        for relative, source in files.items():
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(dedent(source).lstrip())
        return Project(tmp_path)

    return make


@dataclass
class Running:
    server: ThreadingHTTPServer
    host: ProjectHost
    project: Path

    def call(
        self, path: str, payload: Any = None, *, agent: bool = False
    ) -> tuple[int, Any]:
        request = Request(
            f"http://127.0.0.1:{self.server.server_address[1]}{path}",
            data=None if payload is None else json.dumps(payload).encode(),
            headers={
                "X-Blueprints-Token": self.host.agent_token if agent else TOKEN,
                "Content-Type": "application/json",
            },
            method="GET" if payload is None else "POST",
        )
        try:
            with urlopen(request, timeout=40) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return response.status, json.loads(body)
        except HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")


@pytest.fixture
def running(tmp_path: Path) -> Iterator[Running]:
    project = tmp_path / "project"
    project.mkdir()
    (project / "shapes.py").write_text(SOURCE)
    host = ProjectHost(cache_dir=tmp_path / "cache")
    server = start_server(
        host,
        TOKEN,
        seen_store=SeenStore(tmp_path / "seen"),
        comment_store=CommentStore(tmp_path / "comments"),
    )
    host.open(project)
    deadline = time.monotonic() + 10
    while not host.status()["ready"]:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    yield Running(server, host, project)
    server.shutdown()
