import gzip
import json
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from code_blueprints.server import ProjectHost, start_server

TOKEN = "secret-token"


@pytest.fixture
def make_server(tmp_path: Path) -> Iterator[ThreadingHTTPServer]:
    project = tmp_path / "project"
    project.mkdir()
    (project / "shapes.py").write_text(
        "class Square:\n    def area(self, side: float) -> float:\n        return side * side\n"
    )
    host = ProjectHost(cache_dir=tmp_path / "cache")
    server = start_server(host, TOKEN)
    yield server
    server.shutdown()


def fetch(
    server: ThreadingHTTPServer, path: str, token: str | None = TOKEN
) -> tuple[int, bytes]:
    request = Request(
        f"http://127.0.0.1:{server.server_address[1]}{path}",
        headers={"X-Blueprints-Token": token} if token else {},
    )
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read()
            return response.status, (
                gzip.decompress(body)
                if response.headers.get("Content-Encoding") == "gzip"
                else body
            )
    except HTTPError as error:
        return error.code, error.read()


def fetch_json(server: ThreadingHTTPServer, path: str) -> Any:
    status, body = fetch(server, path)
    assert status == 200, body
    return json.loads(body)


def make_opened(server: ThreadingHTTPServer, tmp_path: Path) -> None:
    fetch_json(server, f"/api/open?root={tmp_path / 'project'}")
    deadline = time.monotonic() + 10
    while not fetch_json(server, "/api/status")["ready"]:
        assert time.monotonic() < deadline
        time.sleep(0.05)


def test_rejects_api_calls_without_the_token(make_server: ThreadingHTTPServer) -> None:
    assert fetch(make_server, "/api/status", token=None)[0] == 403
    assert fetch(make_server, "/api/status", token="wrong")[0] == 403


def test_serves_the_page_without_a_token(make_server: ThreadingHTTPServer) -> None:
    status, body = fetch(make_server, "/", token=None)

    assert status == 200
    assert b"app.js" in body


def test_refuses_paths_outside_the_static_folder(
    make_server: ThreadingHTTPServer,
) -> None:
    assert fetch(make_server, "/../server.py", token=None)[0] == 404
    assert fetch(make_server, "/%2e%2e/server.py", token=None)[0] == 404


def test_reports_nothing_open_at_start(make_server: ThreadingHTTPServer) -> None:
    assert fetch_json(make_server, "/api/status")["open"] is False


def test_refuses_to_open_a_missing_folder(
    make_server: ThreadingHTTPServer, tmp_path: Path
) -> None:
    assert fetch(make_server, f"/api/open?root={tmp_path / 'nowhere'}")[0] == 400


def test_serves_overview_of_opened_folder(
    make_server: ThreadingHTTPServer, tmp_path: Path
) -> None:
    make_opened(make_server, tmp_path)

    overview = fetch_json(make_server, "/api/project")
    assert [s["qual"] for s in overview["modules"][0]["symbols"]] == ["Square"]


def test_serves_function_code_and_graph(
    make_server: ThreadingHTTPServer, tmp_path: Path
) -> None:
    make_opened(make_server, tmp_path)

    payload = fetch_json(make_server, "/api/function?path=shapes.py&qual=Square.area")
    assert payload["code"][-1] == [3, "        return side * side"]
    assert {node["kind"] for node in payload["graph"]["nodes"]} >= {"entry", "return"}


def test_answers_not_found_for_unknown_functions(
    make_server: ThreadingHTTPServer, tmp_path: Path
) -> None:
    make_opened(make_server, tmp_path)

    assert fetch(make_server, "/api/function?path=shapes.py&qual=Circle.area")[0] == 404
    assert fetch(make_server, "/api/function?path=../etc/passwd&qual=x")[0] == 404


def test_reuses_cached_overview_for_unchanged_files(
    make_server: ThreadingHTTPServer, tmp_path: Path
) -> None:
    make_opened(make_server, tmp_path)
    cached = list((tmp_path / "cache").glob("*.json.gz"))
    first = fetch_json(make_server, "/api/project")
    make_opened(make_server, tmp_path)

    assert len(cached) == 1
    assert fetch_json(make_server, "/api/project") == first
