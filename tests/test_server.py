import gzip
import subprocess
import json
import threading
import time
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from turtlemap.projects.comparison import head_project
from turtlemap.projects.host import ProjectHost
from turtlemap.projects.seen import SeenStore
from turtlemap.web.server import start_server

TOKEN = "secret-token"


@pytest.fixture
def make_server(tmp_path: Path) -> Iterator[ThreadingHTTPServer]:
    project = tmp_path / "project"
    project.mkdir()
    (project / "shapes.py").write_text(
        "class Square:\n    def area(self, side: float) -> float:\n        return side * side\n"
    )
    server = make_started(tmp_path)
    yield server
    server.shutdown()


def make_started(tmp_path: Path) -> ThreadingHTTPServer:
    host = ProjectHost(cache_dir=tmp_path / "cache")
    return start_server(host, TOKEN, seen_store=SeenStore(tmp_path / "seen"))


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


def post_json(server: ThreadingHTTPServer, path: str, payload: Any) -> Any:
    request = Request(
        f"http://127.0.0.1:{server.server_address[1]}{path}",
        data=json.dumps(payload).encode(),
        headers={"X-Blueprints-Token": TOKEN, "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        body = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return json.loads(body)


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


def test_answers_project_events_with_the_current_revision(
    make_server: ThreadingHTTPServer, tmp_path: Path
) -> None:
    make_opened(make_server, tmp_path)
    revision = fetch_json(make_server, "/api/status")["revision"]

    answer = fetch_json(make_server, f"/api/project/events?since={revision}&wait=0")

    assert answer["revision"] == revision
    assert answer["ready"]


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


def test_a_slow_earlier_comparison_does_not_replace_a_later_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = make_opened_host(tmp_path)
    held = make_held_head(monkeypatch, hold_call=1)

    host.open_diff("main..feature")
    host.open_diff("main")
    expect_host_ready(host)
    held.release.set()
    assert held.finished.wait(10)
    time.sleep(0.3)

    expect_comparing(host, "main")


def test_an_earlier_comparison_does_not_win_over_a_slower_later_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = make_opened_host(tmp_path)
    held = make_held_head(monkeypatch, hold_call=2)

    host.open_diff("main")
    host.open_diff("main..feature")
    time.sleep(0.5)
    held.release.set()
    assert held.finished.wait(10)

    expect_comparing(host, "main..feature")


@dataclass
class HeldHead:
    release: threading.Event
    finished: threading.Event


def make_held_head(monkeypatch: pytest.MonkeyPatch, hold_call: int) -> HeldHead:
    held = HeldHead(threading.Event(), threading.Event())
    calls: list[int] = []

    def hold(*args: Any) -> Any:
        calls.append(len(calls) + 1)
        holding = len(calls) == hold_call
        if holding:
            held.release.wait(10)
        result = head_project(*args)
        if holding:
            held.finished.set()
        return result

    monkeypatch.setattr("turtlemap.projects.host.head_project", hold)
    return held


def make_opened_host(tmp_path: Path) -> ProjectHost:
    host = ProjectHost(cache_dir=tmp_path / "cache")
    host.open(make_git_project(tmp_path))
    expect_host_ready(host)
    return host


def expect_comparing(host: ProjectHost, spec: str) -> None:
    expect_host_ready(host)
    assert host.status()["diff"]["spec"] == spec
    diff = host.session().diff
    assert diff is not None
    assert diff.range.spec == spec


def expect_host_ready(host: ProjectHost) -> None:
    deadline = time.monotonic() + 20
    while not (status := host.status())["ready"]:
        assert status["error"] is None, status["error"]
        assert time.monotonic() < deadline
        time.sleep(0.05)


def test_lists_branches(make_server: ThreadingHTTPServer, tmp_path: Path) -> None:
    fetch_json(make_server, f"/api/open?root={make_git_project(tmp_path)}")

    assert set(fetch_json(make_server, "/api/branches")["branches"]) == {
        "main",
        "feature",
    }


def make_working_copy_of_feature(tmp_path: Path) -> Path:
    folder = make_git_project(tmp_path)
    subprocess.run(
        ["git", "checkout", "-q", "feature"],
        cwd=folder,
        check=True,
        capture_output=True,
    )
    return folder


def expect_ready(server: ThreadingHTTPServer) -> None:
    deadline = time.monotonic() + 20
    while not (status := fetch_json(server, "/api/status"))["ready"]:
        assert status["error"] is None, status["error"]
        assert time.monotonic() < deadline
        time.sleep(0.05)


def test_lists_review_units_for_a_comparison(
    make_server: ThreadingHTTPServer, tmp_path: Path
) -> None:
    make_compared(make_server, make_git_project(tmp_path), "main..feature")

    units = fetch_json(make_server, "/api/diff/data")["units"]["shapes.py"]
    assert [(unit["id"], unit["diff"]) for unit in units] == [
        ("fn:shapes.py:area", "modified"),
        ("fn:shapes.py:perimeter", "added"),
    ]
    assert fetch_json(make_server, "/api/seen") == {"seen": []}


def test_only_the_function_that_changed_since_is_unseen(
    make_server: ThreadingHTTPServer, tmp_path: Path
) -> None:
    folder = make_working_copy_of_feature(tmp_path)
    make_compared(make_server, folder, "main")
    post_json(
        make_server,
        "/api/seen",
        {"ids": ["fn:shapes.py:area", "fn:shapes.py:perimeter"], "seen": True},
    )
    shapes = folder / "shapes.py"
    shapes.write_text(shapes.read_text().replace("4 * side", "side * 4"))
    fetch_json(make_server, "/api/reload")
    expect_ready(make_server)

    assert fetch_json(make_server, "/api/seen") == {"seen": ["fn:shapes.py:area"]}


def test_unmarking_forgets_a_seen_function(
    make_server: ThreadingHTTPServer, tmp_path: Path
) -> None:
    make_compared(make_server, make_git_project(tmp_path), "main..feature")
    post_json(
        make_server,
        "/api/seen",
        {"ids": ["fn:shapes.py:area", "fn:shapes.py:perimeter"], "seen": True},
    )

    assert post_json(
        make_server, "/api/seen", {"ids": ["fn:shapes.py:area"], "seen": False}
    ) == {"seen": ["fn:shapes.py:perimeter"]}


def test_keeps_seen_functions_on_disk_between_runs(tmp_path: Path) -> None:
    folder = make_git_project(tmp_path)
    first = make_started(tmp_path)
    make_compared(first, folder, "main..feature")
    post_json(first, "/api/seen", {"ids": ["fn:shapes.py:area"], "seen": True})
    first.shutdown()
    second = make_started(tmp_path)
    make_compared(second, folder, "main..feature")

    assert fetch_json(second, "/api/seen") == {"seen": ["fn:shapes.py:area"]}
    second.shutdown()


def test_refuses_to_mark_without_the_token(
    make_server: ThreadingHTTPServer, tmp_path: Path
) -> None:
    request = Request(
        f"http://127.0.0.1:{make_server.server_address[1]}/api/seen",
        data=b'{"ids": []}',
        method="POST",
    )

    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=10)
    assert error.value.code == 403
