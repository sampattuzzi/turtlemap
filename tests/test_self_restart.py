import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from urllib.request import Request, urlopen

import turtlemap.app

PACKAGE = Path(turtlemap.app.__file__).resolve().parent
OLD_GREETING = "Press Ctrl+C to stop."
NEW_GREETING = "Press Ctrl+C to stop the new version."


def test_restarts_itself_on_the_same_address_with_the_new_code(
    tmp_path: Path,
) -> None:
    install, upstream = make_installed(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "shapes.py").write_text("class Square:\n    side = 1\n")
    make_pushed(upstream, OLD_GREETING, NEW_GREETING)
    lines: "queue.Queue[str]" = queue.Queue()
    running = subprocess.Popen(
        [sys.executable, "-m", "turtlemap.app", str(project), "--no-open"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(install)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    threading.Thread(target=make_read, args=(running, lines), daemon=True).start()
    try:
        before = expect_line(lines, "running at")
        expect_line(lines, OLD_GREETING)
        expect_line(lines, "updated itself")
        after = expect_line(lines, "running at")
        expect_line(lines, NEW_GREETING)

        assert printed_url(after) == printed_url(before)
        assert expect_status(printed_url(after))["open"]
    finally:
        running.terminate()
        running.wait(timeout=10)


def make_installed(tmp_path: Path) -> tuple[Path, Path]:
    upstream = tmp_path / "upstream"
    origin = tmp_path / "origin.git"
    install = tmp_path / "install"
    shutil.copytree(
        PACKAGE, upstream / "turtlemap", ignore=shutil.ignore_patterns("__pycache__")
    )
    git(upstream, "init", "-q", "-b", "main")
    make_identity(upstream)
    git(upstream, "add", "-A")
    git(upstream, "commit", "-q", "-m", "first")
    git(tmp_path, "clone", "-q", "--bare", str(upstream), str(origin))
    git(upstream, "remote", "add", "origin", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(install))
    return install, upstream


def make_pushed(upstream: Path, old: str, new: str) -> None:
    app = upstream / "turtlemap" / "app.py"
    app.write_text(app.read_text().replace(old, new))
    git(upstream, "commit", "-q", "-am", "new greeting")
    git(upstream, "push", "-q", "origin", "main")


def make_identity(folder: Path) -> None:
    git(folder, "config", "user.email", "test@example.com")
    git(folder, "config", "user.name", "Test")
    git(folder, "config", "commit.gpgsign", "false")


def make_read(running: "subprocess.Popen[str]", lines: "queue.Queue[str]") -> None:
    assert running.stdout is not None
    for line in running.stdout:
        lines.put(line.rstrip("\n"))


def expect_line(lines: "queue.Queue[str]", wanted: str) -> str:
    seen: list[str] = []
    while True:
        try:
            line = lines.get(timeout=60)
        except queue.Empty:
            raise AssertionError(f"never printed {wanted!r}; printed {seen}")
        seen.append(line)
        if wanted in line:
            return line


def expect_status(url: str) -> dict[str, object]:
    address, token = url.split("/?t=", 1)
    request = Request(f"{address}/api/status", headers={"X-Blueprints-Token": token})
    with urlopen(request, timeout=10) as response:
        status: dict[str, object] = json.loads(response.read())
    return status


def printed_url(line: str) -> str:
    return line.split("running at ", 1)[1].strip()


def git(folder: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=folder, check=True, capture_output=True, text=True
    ).stdout
