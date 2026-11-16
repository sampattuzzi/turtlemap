import gzip
import subprocess
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


def make_git_project(tmp_path: Path) -> Path:
    folder = tmp_path / "gitproject"
    folder.mkdir()

    def git(*arguments: str) -> None:
        subprocess.run(["git", *arguments], cwd=folder, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (folder / "shapes.py").write_text(
        "def area(side: float) -> float:\n    return side * side\n"
    )
    git("add", "-A")
    git("commit", "-q", "-m", "first")
    git("checkout", "-q", "-b", "feature")
    (folder / "shapes.py").write_text(
        "def area(side: float) -> float:\n    return round(side * side, 2)\n\n\ndef perimeter(side: float) -> float:\n    return 4 * side\n"
    )
    git("commit", "-q", "-am", "second")
    git("checkout", "-q", "main")
    return folder


def make_compared(server: ThreadingHTTPServer, folder: Path, spec: str) -> None:
    fetch_json(server, f"/api/open?root={folder}")
    fetch_json(server, f"/api/diff?spec={spec}")
    deadline = time.monotonic() + 20
    while not (status := fetch_json(server, "/api/status"))["ready"]:
        assert status["error"] is None, status["error"]
        assert time.monotonic() < deadline
        time.sleep(0.05)


def test_compares_a_git_range(make_server: ThreadingHTTPServer, tmp_path: Path) -> None:
    make_compared(make_server, make_git_project(tmp_path), "main..feature")

    data = fetch_json(make_server, "/api/diff/data")
    assert data["files"] == {"shapes.py": {"status": "modified"}}
    assert data["status"]["fn:shapes.py:perimeter"] == "added"
    assert data["status"]["fn:shapes.py:area"] == "modified"
    assert fetch_json(make_server, "/api/status")["diff"]["spec"] == "main..feature"


def test_shows_the_head_revision_while_comparing(
    make_server: ThreadingHTTPServer, tmp_path: Path
) -> None:
    make_compared(make_server, make_git_project(tmp_path), "main..feature")

    overview = fetch_json(make_server, "/api/project")
    assert [s["qual"] for s in overview["modules"][0]["symbols"]] == [
        "area",
        "perimeter",
    ]
    payload = fetch_json(make_server, "/api/function?path=shapes.py&qual=area")
    assert [row[2] for row in payload["code"] if len(row) > 2] == ["removed", "added"]


def test_reports_bad_ranges(make_server: ThreadingHTTPServer, tmp_path: Path) -> None:
    fetch_json(make_server, f"/api/open?root={make_git_project(tmp_path)}")

    status, body = fetch(make_server, "/api/diff?spec=main..missing")
    assert status == 400
    assert b"Unknown revision" in body


def test_clearing_the_comparison_returns_to_the_working_copy(
    make_server: ThreadingHTTPServer, tmp_path: Path
) -> None:
    folder = make_git_project(tmp_path)
    make_compared(make_server, folder, "main..feature")
    fetch_json(make_server, "/api/diff?spec=")
    deadline = time.monotonic() + 10
    while not fetch_json(make_server, "/api/status")["ready"]:
        assert time.monotonic() < deadline
        time.sleep(0.05)

    assert fetch_json(make_server, "/api/status")["diff"] is None
    assert [
        s["qual"]
        for s in fetch_json(make_server, "/api/project")["modules"][0]["symbols"]
    ] == ["area"]


def test_lists_branches(make_server: ThreadingHTTPServer, tmp_path: Path) -> None:
    fetch_json(make_server, f"/api/open?root={make_git_project(tmp_path)}")

    assert set(fetch_json(make_server, "/api/branches")["branches"]) == {
        "main",
        "feature",
    }
