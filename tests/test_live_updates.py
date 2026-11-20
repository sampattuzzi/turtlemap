import gzip
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from collections.abc import Callable
from typing import Any

import pytest

from turtlemap.projects.host import KEPT_CHANGES, ProjectHost, Session
from turtlemap.projects.watcher import ProjectWatcher

SQUARE = "class Square:\n    def area(self, side: float) -> float:\n        return side * side\n"
CIRCLE = SQUARE + "\n\nclass Circle:\n    pass\n"
DRAWING = (
    "from shapes import Square\n\n\ndef draw() -> float:\n    return Square().area(2)\n"
)
NOTES = "import json\n\n\ndef remember() -> str:\n    return json.dumps('milk')\n"


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


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="inotify")
def test_watcher_leaves_ignored_folders_unwatched(tmp_path: Path) -> None:
    make_file(tmp_path / "app" / "main.py", "x = 1\n")
    for package in range(50):
        (tmp_path / "node_modules" / f"package{package}" / "lib").mkdir(parents=True)
    before = inotify_watches()
    watcher = ProjectWatcher(lambda: None)

    watcher.watch(tmp_path)
    watching = inotify_watches() - before
    watcher.stop()

    assert watching == 2


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="inotify")
def test_watcher_follows_folders_made_after_it_started(tmp_path: Path) -> None:
    calls: list[float] = []
    watcher = ProjectWatcher(lambda: calls.append(time.monotonic()), delay=0.05)
    watcher.watch(tmp_path)
    (tmp_path / "app").mkdir()
    time.sleep(0.5)
    calls.clear()

    make_file(tmp_path / "app" / "main.py", "x = 1\n")

    expect_eventually(lambda: calls)
    watcher.stop()


def test_changes_hold_only_the_files_an_edit_reached(tmp_path: Path) -> None:
    host = make_opened_host(tmp_path, {"drawing.py": DRAWING, "notes.py": NOTES})
    before = host.status()["revision"]
    (tmp_path / "project" / "notes.py").write_text(NOTES + "\n\nSHOPPING = 1\n")

    host.refresh()

    changes = expect_changes(host, before)
    assert changes["rebuilt"] == ["notes.py"]
    assert [module["path"] for module in changes["modules"]] == ["notes.py"]
    assert changes["removed"] == []


def test_changes_carry_the_edges_of_each_rebuilt_file(tmp_path: Path) -> None:
    host = make_opened_host(tmp_path, {"drawing.py": DRAWING})
    before = host.status()["revision"]
    (tmp_path / "project" / "drawing.py").write_text(DRAWING + "\n\nSIDE = 2\n")

    host.refresh()

    edges = expect_changes(host, before)["edges"]
    assert [path for path, count in edges["files"]] == ["drawing.py"]
    assert sum(count for path, count in edges["files"]) == len(edges["rows"])
    assert "fn:drawing.py:draw" in edges["ids"]


def test_changes_name_a_deleted_file_as_removed(tmp_path: Path) -> None:
    host = make_opened_host(tmp_path, {"notes.py": NOTES})
    before = host.status()["revision"]
    (tmp_path / "project" / "notes.py").unlink()

    host.refresh()

    changes = expect_changes(host, before)
    assert changes["removed"] == ["notes.py"]
    assert changes["modules"] == []


def test_changes_list_every_library_still_in_use(tmp_path: Path) -> None:
    host = make_opened_host(tmp_path, {"notes.py": NOTES})
    before = host.status()["revision"]
    (tmp_path / "project" / "shapes.py").write_text(CIRCLE)

    host.refresh()

    libraries = expect_changes(host, before)["libraries"]
    assert [library["id"] for library in libraries] == ["lib:stdlib"]


def test_changes_gather_every_refresh_since_the_given_revision(
    tmp_path: Path,
) -> None:
    host = make_opened_host(tmp_path, {"notes.py": NOTES})
    before = host.status()["revision"]
    (tmp_path / "project" / "shapes.py").write_text(CIRCLE)
    host.refresh()
    (tmp_path / "project" / "notes.py").write_text(NOTES + "\n\nSHOPPING = 1\n")
    host.refresh()

    assert expect_changes(host, before)["rebuilt"] == ["notes.py", "shapes.py"]


def test_changes_since_the_current_revision_are_empty(tmp_path: Path) -> None:
    host = make_opened_host(tmp_path)

    changes = expect_changes(host, host.status()["revision"])

    assert (changes["rebuilt"], changes["removed"]) == ([], [])


def test_changes_from_before_the_project_was_read_need_the_full_overview(
    tmp_path: Path,
) -> None:
    host = make_opened_host(tmp_path)

    assert host.changes_since(0) is None


def test_changes_need_the_full_overview_once_too_many_refreshes_have_passed() -> None:
    session = Session(revision=1, changes_from=1)
    for count in range(KEPT_CHANGES + 1):
        session = replace(
            session.changed(frozenset({f"file{count}.py"})),
            revision=session.revision + 1,
        )

    assert session.touched_since(1) is None
    assert session.touched_since(2) is not None
    assert session.touched_since(session.revision - 1) == frozenset(
        {f"file{KEPT_CHANGES}.py"}
    )


def test_a_comparison_with_the_working_copy_follows_edits(tmp_path: Path) -> None:
    host = make_compared_host(tmp_path, "HEAD")
    before = host.status()["revision"]
    (tmp_path / "project" / "shapes.py").write_text(CIRCLE)

    host.refresh()

    assert host.status()["revision"] > before
    assert host.status()["diff"]["ready"]
    assert compared_status(host, "cls:shapes.py:Circle") == "added"
    assert host.changes_since(before) is None


def test_a_comparison_that_fails_after_an_edit_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = make_compared_host(tmp_path, "HEAD")
    before = host.status()["revision"]
    (tmp_path / "project" / "shapes.py").write_text(CIRCLE)
    monkeypatch.setattr("turtlemap.projects.host.compare", fail_to_compare)

    host.refresh()

    assert host.status()["revision"] > before
    assert "git went away" in host.status()["error"]
    assert class_names(host) == ["Square", "Circle"]


def test_a_comparison_between_commits_ignores_edits(tmp_path: Path) -> None:
    host = make_compared_host(tmp_path, "HEAD..HEAD")
    before = host.status()["revision"]
    (tmp_path / "project" / "shapes.py").write_text(CIRCLE)

    host.refresh()

    assert host.status()["revision"] == before


def make_opened_host(
    tmp_path: Path, files: dict[str, str] | None = None
) -> ProjectHost:
    for name, text in {"shapes.py": SQUARE, **(files or {})}.items():
        make_file(tmp_path / "project" / name, text)
    host = ProjectHost(cache_dir=tmp_path / "cache")
    host.open(tmp_path / "project")
    expect_eventually(lambda: host.status()["ready"])
    return host


def make_compared_host(tmp_path: Path, spec: str) -> ProjectHost:
    folder = tmp_path / "project"
    make_file(folder / "shapes.py", SQUARE)
    for arguments in [
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        ["-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-qm", "1"],
    ]:
        subprocess.run(["git", *arguments], cwd=folder, check=True)
    host = ProjectHost(cache_dir=tmp_path / "cache")
    host.open(folder, spec)
    expect_eventually(lambda: host.status()["ready"])
    return host


def fail_to_compare(*arguments: object) -> object:
    raise RuntimeError("git went away")


def expect_changes(host: ProjectHost, since: int) -> dict[str, Any]:
    changes = host.changes_since(since)
    assert changes is not None
    assert changes["revision"] == host.status()["revision"]
    return changes


def compared_status(host: ProjectHost, node: str) -> str | None:
    diff = host.session().diff
    assert diff is not None
    return diff.status.get(node)


def inotify_watches() -> int:
    total = 0
    for descriptor in os.listdir("/proc/self/fd"):
        try:
            if os.readlink(f"/proc/self/fd/{descriptor}") != "anon_inode:inotify":
                continue
            info = Path(f"/proc/self/fdinfo/{descriptor}").read_text()
        except OSError:
            continue
        total += sum(line.startswith("inotify wd:") for line in info.splitlines())
    return total


def make_edit(host: ProjectHost, tmp_path: Path) -> None:
    (tmp_path / "project" / "shapes.py").write_text(CIRCLE)
    host.refresh()


def make_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def class_names(host: ProjectHost) -> list[str]:
    data = host.session().overview
    assert data is not None
    overview: dict[str, Any] = json.loads(gzip.decompress(data.compressed()))
    return [symbol["name"] for symbol in overview["modules"][0]["symbols"]]


def expect_eventually(check: Callable[[], object], seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline
        time.sleep(0.05)
