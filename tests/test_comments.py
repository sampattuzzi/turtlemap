import threading
import time
from pathlib import Path
from typing import Any

import pytest

from code_blueprints.comments import AGENT, USER, CommentError, CommentStore

ANCHOR = {"view": "code", "path": "shop/models.py", "start": 3, "end": 4}


def make_store(tmp_path: Path) -> CommentStore:
    return CommentStore(tmp_path / "comments")


def make_thread(store: CommentStore, root: Path, body: str = "Why?") -> dict[str, Any]:
    return store.create(root, USER, ANCHOR, body)


def test_keeps_comments_on_disk_per_project(tmp_path: Path) -> None:
    root = tmp_path / "project"
    thread = make_thread(make_store(tmp_path), root)

    again = make_store(tmp_path).threads(root)

    assert [t["id"] for t in again] == [thread["id"]]
    assert again[0]["messages"][0]["body"] == "Why?"
    assert make_store(tmp_path).threads(tmp_path / "other") == []


def test_only_the_user_can_resolve(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    thread = make_thread(store, tmp_path)

    with pytest.raises(CommentError) as refused:
        store.resolve(tmp_path, thread["id"], AGENT, True)

    assert refused.value.status == 403
    assert store.resolve(tmp_path, thread["id"], USER, True)["resolved"] is True


def test_only_an_agent_can_report_progress(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    thread = make_thread(store, tmp_path)

    with pytest.raises(CommentError):
        store.mark(tmp_path, [thread["id"]], USER, "seen")

    marked = store.mark(tmp_path, [thread["id"]], AGENT, "working", "updating plots.py")
    assert marked[0]["agent"]["state"] == "working"
    assert marked[0]["agent"]["note"] == "updating plots.py"
    assert store.agent(tmp_path)["note"] == "updating plots.py"


def test_a_user_reply_makes_the_thread_unseen_again(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    thread = make_thread(store, tmp_path)
    store.mark(tmp_path, [thread["id"]], AGENT, "done")

    replied = store.reply(tmp_path, thread["id"], USER, "Still wrong")

    assert replied["agent"]["state"] is None
    assert [m["author"] for m in replied["messages"]] == [USER, USER]


def test_an_agent_reply_keeps_its_progress(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    thread = make_thread(store, tmp_path)
    store.mark(tmp_path, [thread["id"]], AGENT, "seen")

    replied = store.reply(tmp_path, thread["id"], AGENT, "Looking")

    assert replied["agent"]["state"] == "seen"


def test_events_wait_for_the_next_change(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    cursor = store.cursor(tmp_path)
    found: list[dict[str, Any]] = []

    def watch() -> None:
        found.append(store.events(tmp_path, cursor, 5, AGENT))

    watcher = threading.Thread(target=watch)
    watcher.start()
    time.sleep(0.2)
    thread = make_thread(store, tmp_path)
    watcher.join(5)

    assert [event["type"] for event in found[0]["events"]] == ["created"]
    assert [t["id"] for t in found[0]["threads"]] == [thread["id"]]
    assert found[0]["cursor"] == cursor + 1


def test_events_return_empty_when_nothing_happens(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    answer = store.events(tmp_path, store.cursor(tmp_path), 0.1, USER)

    assert answer["events"] == []


def test_rejects_comments_without_a_place_or_text(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(CommentError):
        store.create(tmp_path, USER, {"view": "nowhere"}, "text")
    with pytest.raises(CommentError):
        store.create(tmp_path, USER, ANCHOR, "   ")
