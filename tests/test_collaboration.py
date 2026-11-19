import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from turtlemap.projects.registry import ServerRegistry, find_server
from tests.conftest import SOURCE, Running


def make_comment(running: Running, anchor: dict[str, Any]) -> dict[str, Any]:
    status, thread = running.call("/api/comments", {"anchor": anchor, "body": "Why?"})
    assert status == 200, thread
    return dict(thread)


def test_places_a_map_comment_on_its_source_lines(running: Running) -> None:
    thread = make_comment(running, {"view": "map", "ids": ["m:shapes.py:Square.area"]})

    assert thread["where"]["locations"] == [
        {
            "id": "m:shapes.py:Square.area",
            "path": "shapes.py",
            "qual": "Square.area",
            "start": 2,
            "end": 3,
        }
    ]
    assert thread["where"]["outdated"] is False


def test_shows_the_source_behind_a_comment(running: Running) -> None:
    thread = make_comment(
        running,
        {
            "view": "code",
            "path": "shapes.py",
            "start": 3,
            "end": 3,
            "text": "        return side * side",
        },
    )

    status, shown = running.call(f"/api/comments/thread?id={thread['id']}", agent=True)

    assert status == 200
    assert shown["where"]["locations"][0]["source"] == [
        [3, "        return side * side"]
    ]


def test_flags_code_comments_whose_lines_changed(running: Running) -> None:
    thread = make_comment(
        running,
        {
            "view": "code",
            "path": "shapes.py",
            "start": 3,
            "end": 3,
            "text": "        return side * side",
        },
    )
    (running.project / "shapes.py").write_text(
        SOURCE.replace("side * side", "side ** 2")
    )
    running.host.reload()
    deadline = time.monotonic() + 10
    while not running.host.status()["ready"]:
        assert time.monotonic() < deadline
        time.sleep(0.05)

    status, listed = running.call("/api/comments")

    assert status == 200
    assert listed["threads"][0]["id"] == thread["id"]
    assert listed["threads"][0]["where"]["outdated"] is True


def test_finds_code_comments_that_moved(running: Running) -> None:
    make_comment(
        running,
        {
            "view": "code",
            "path": "shapes.py",
            "start": 3,
            "end": 3,
            "text": "        return side * side",
        },
    )
    (running.project / "shapes.py").write_text("import math\n\n" + SOURCE)
    running.host.reload()
    deadline = time.monotonic() + 10
    while not running.host.status()["ready"]:
        assert time.monotonic() < deadline
        time.sleep(0.05)

    where = running.call("/api/comments")[1]["threads"][0]["where"]

    assert where["moved"] is True
    assert where["locations"][0]["start"] == 5


def test_agent_replies_but_cannot_resolve(running: Running) -> None:
    thread = make_comment(running, {"view": "map", "ids": ["mod:shapes.py"]})

    replied = running.call(
        "/api/comments/reply", {"id": thread["id"], "body": "On it"}, agent=True
    )
    refused = running.call(
        "/api/comments/resolve", {"id": thread["id"], "resolved": True}, agent=True
    )
    resolved = running.call("/api/comments/resolve", {"id": thread["id"]})

    assert replied[0] == 200
    assert [m["author"] for m in replied[1]["messages"]] == ["user", "agent"]
    assert refused[0] == 403
    assert resolved[1]["resolved"] is True


def test_agent_reports_what_it_is_working_on(running: Running) -> None:
    thread = make_comment(running, {"view": "map", "ids": ["mod:shapes.py"]})

    status, marked = running.call(
        "/api/comments/progress",
        {"ids": [thread["id"]], "state": "working", "note": "updating shapes.py"},
        agent=True,
    )
    listed = running.call("/api/comments")[1]

    assert status == 200
    assert marked["threads"][0]["agent"]["state"] == "working"
    assert listed["agent"]["note"] == "updating shapes.py"


def test_rejects_unknown_tokens(running: Running) -> None:
    request = Request(
        f"http://127.0.0.1:{running.server.server_address[1]}/api/comments",
        headers={"X-Blueprints-Token": "nope"},
    )

    with pytest.raises(HTTPError) as refused:
        urlopen(request, timeout=10)
    assert refused.value.code == 403


def test_watching_agents_hear_about_new_comments(running: Running) -> None:
    cursor = running.call("/api/comments", agent=True)[1]["cursor"]
    make_comment(running, {"view": "map", "ids": ["mod:shapes.py"]})

    status, answer = running.call(
        f"/api/comments/events?since={cursor}&wait=5", agent=True
    )

    assert status == 200
    assert [event["type"] for event in answer["events"]] == ["created"]
    assert answer["agent"]["polled"] > 0


def test_finds_the_server_hosting_a_folder(tmp_path: Path) -> None:
    registry = ServerRegistry(tmp_path / "servers")
    registry.publish("http://127.0.0.1:1234", "agent-token")
    registry.set_root(tmp_path / "project")

    found = find_server(tmp_path / "project" / "pkg", tmp_path / "servers")
    registry.remove()

    assert found is not None
    assert found.url == "http://127.0.0.1:1234"
    assert found.token == "agent-token"
    assert find_server(tmp_path / "project", tmp_path / "servers") is None
