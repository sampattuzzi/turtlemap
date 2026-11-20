import gzip
import json
import os
import threading
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any

from turtlemap.projects.host import ProjectHost
from turtlemap.projects.watcher import ProjectWatcher

SQUARE = "class Square:\n    def area(self, side: float) -> float:\n        return side * side\n"
CIRCLE = SQUARE + "\n\nclass Circle:\n    pass\n"


def test_reload_swaps_in_the_edited_project(tmp_path: Path) -> None:
    host = make_opened_host(tmp_path)
    before = host.status()["revision"]
    (tmp_path / "project" / "shapes.py").write_text(CIRCLE)

    host.reload()

    assert host.status()["revision"] > before
    assert host.status()["edited"] == ["shapes.py"]
    assert class_names(host) == ["Square", "Circle"]


def test_reload_keeps_the_revision_when_a_file_is_saved_unchanged(
    tmp_path: Path,
) -> None:
    host = make_opened_host(tmp_path)
    before = host.status()["revision"]
    later = time.time() + 60
    os.utime(tmp_path / "project" / "shapes.py", (later, later))

    host.reload()

    assert host.status()["revision"] == before


def test_waiting_returns_as_soon_as_the_project_changes(tmp_path: Path) -> None:
    host = make_opened_host(tmp_path)
    before = host.status()["revision"]
    threading.Timer(0.2, make_edit, (host, tmp_path)).start()

    started = time.monotonic()
    status = host.wait_for_change(before, 10)

    assert status["revision"] > before
    assert time.monotonic() - started < 5


def test_waiting_gives_up_when_nothing_changes(tmp_path: Path) -> None:
    host = make_opened_host(tmp_path)
    before = host.status()["revision"]

    assert host.wait_for_change(before, 0.1)["revision"] == before


def test_refreshes_by_itself_after_a_source_file_is_saved(tmp_path: Path) -> None:
    host = make_opened_host(tmp_path)
    host.watch_files()
    time.sleep(0.5)
    (tmp_path / "project" / "shapes.py").write_text(CIRCLE)

    expect_eventually(lambda: class_names(host) == ["Square", "Circle"])


def test_watcher_reacts_only_to_source_files(tmp_path: Path) -> None:
    calls: list[float] = []
    watcher = ProjectWatcher(lambda: calls.append(time.monotonic()), delay=0.05)
    watcher.watch(tmp_path)
    time.sleep(0.5)
    for ignored in ["notes.txt", ".git/HEAD", "node_modules/lib/x.py"]:
        make_file(tmp_path / ignored, "x = 1\n")
    time.sleep(1)
    ignored_calls = len(calls)
    make_file(tmp_path / "app" / "main.py", "x = 1\n")

    expect_eventually(lambda: len(calls) > ignored_calls)
    watcher.stop()
    assert ignored_calls == 0


def make_opened_host(tmp_path: Path) -> ProjectHost:
    make_file(tmp_path / "project" / "shapes.py", SQUARE)
    host = ProjectHost(cache_dir=tmp_path / "cache")
    host.open(tmp_path / "project")
    expect_eventually(lambda: host.status()["ready"])
    return host


def make_edit(host: ProjectHost, tmp_path: Path) -> None:
    (tmp_path / "project" / "shapes.py").write_text(CIRCLE)
    host.refresh()


def make_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def class_names(host: ProjectHost) -> list[str]:
    data = host.session().overview_bytes
    assert data is not None
    overview: dict[str, Any] = json.loads(gzip.decompress(data))
    return [symbol["name"] for symbol in overview["modules"][0]["symbols"]]


def expect_eventually(check: Callable[[], object], seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline
        time.sleep(0.05)
