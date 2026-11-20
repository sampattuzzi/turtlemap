import json
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import Request, urlopen

from turtlemap.projects.host import ProjectHost
from turtlemap.updates.checkout import Checkout
from turtlemap.updates.relaunch import Launch, relaunch_arguments
from turtlemap.updates.updater import Outcome, SelfUpdater, UpdateNotice
from turtlemap.web.server import start_server

FILES = {
    "turtlemap/app.py": "print('one')\n",
    "turtlemap/static/app.js": "console.log('one');\n",
    "pyproject.toml": "[tool.poetry]\n",
    "README.md": "One\n",
}


@dataclass
class Installed:
    folder: Path
    upstream: Path
    notice: UpdateNotice
    updater: SelfUpdater
    restarts: list[str] = field(default_factory=list)

    def push(self, files: dict[str, str]) -> str:
        make_files(self.upstream, files)
        git(self.upstream, "add", "-A")
        git(self.upstream, "commit", "-q", "-m", "upstream change")
        git(self.upstream, "push", "-q", "origin", "main")
        return git(self.upstream, "rev-parse", "HEAD").strip()

    def head(self) -> str:
        return git(self.folder, "rev-parse", "HEAD").strip()


def test_pulls_a_browser_change_and_tells_the_page(tmp_path: Path) -> None:
    installed = make_installed(tmp_path)
    latest = installed.push({"turtlemap/static/app.js": "console.log('two');\n"})

    assert installed.updater.check() is Outcome.UPDATED

    assert installed.head() == latest
    assert installed.notice.state()["version"] == latest
    assert installed.restarts == []


def test_restarts_after_pulling_a_server_change(tmp_path: Path) -> None:
    installed = make_installed(tmp_path)
    latest = installed.push({"turtlemap/app.py": "print('two')\n"})

    assert installed.updater.check() is Outcome.RESTARTING

    assert installed.head() == latest
    assert installed.restarts == ["restart"]


def test_pulls_a_change_outside_the_app_without_restarting(tmp_path: Path) -> None:
    installed = make_installed(tmp_path)
    latest = installed.push({"README.md": "Two\n"})

    assert installed.updater.check() is Outcome.UPDATED

    assert installed.head() == latest
    assert installed.restarts == []


def test_leaves_a_dependency_change_for_the_user_to_install(tmp_path: Path) -> None:
    installed = make_installed(tmp_path)
    before = installed.head()
    latest = installed.push(
        {"pyproject.toml": "[tool.poetry]\nname = 'x'\n", "turtlemap/app.py": "2\n"}
    )

    assert installed.updater.check() is Outcome.NEEDS_INSTALL

    assert installed.head() == before
    assert installed.notice.state()["waiting"] == {
        "commit": latest,
        "folder": str(installed.folder.resolve()),
    }
    assert installed.restarts == []


def test_does_nothing_when_main_has_not_moved(tmp_path: Path) -> None:
    installed = make_installed(tmp_path)

    assert installed.updater.check() is Outcome.UP_TO_DATE


def test_leaves_local_edits_alone(tmp_path: Path) -> None:
    installed = make_installed(tmp_path)
    before = installed.head()
    installed.push({"turtlemap/app.py": "print('two')\n"})
    make_files(installed.folder, {"turtlemap/app.py": "print('mine')\n"})

    assert installed.updater.check() is Outcome.SKIPPED

    assert installed.head() == before


def test_leaves_local_commits_alone(tmp_path: Path) -> None:
    installed = make_installed(tmp_path)
    installed.push({"turtlemap/app.py": "print('two')\n"})
    make_files(installed.folder, {"turtlemap/extra.py": "x = 1\n"})
    git(installed.folder, "add", "-A")
    git(installed.folder, "commit", "-q", "-m", "mine")
    mine = installed.head()

    assert installed.updater.check() is Outcome.SKIPPED

    assert installed.head() == mine


def test_counts_local_commits_ahead_of_main_as_up_to_date(tmp_path: Path) -> None:
    installed = make_installed(tmp_path)
    make_files(installed.folder, {"turtlemap/extra.py": "x = 1\n"})
    git(installed.folder, "add", "-A")
    git(installed.folder, "commit", "-q", "-m", "mine")

    assert installed.updater.check() is Outcome.UP_TO_DATE


def test_leaves_other_branches_alone(tmp_path: Path) -> None:
    installed = make_installed(tmp_path)
    git(installed.folder, "checkout", "-q", "-b", "feature")
    before = installed.head()
    installed.push({"turtlemap/app.py": "print('two')\n"})

    assert installed.updater.check() is Outcome.SKIPPED

    assert installed.head() == before


def test_only_a_checkout_root_can_update_itself(tmp_path: Path) -> None:
    installed = make_installed(tmp_path)

    assert Checkout(installed.folder).is_repository_root()
    assert not Checkout(installed.folder / "turtlemap").is_repository_root()
    assert not Checkout(tmp_path).is_repository_root()


def test_a_waiting_page_hears_about_a_new_version() -> None:
    notice = UpdateNotice("old")
    threading.Timer(0.1, notice.announce_version, args=("new",)).start()

    state = notice.wait_for_change("old", "", 5)

    assert state["version"] == "new"


def test_a_waiting_page_gives_up_when_nothing_changes() -> None:
    notice = UpdateNotice("old")

    assert notice.wait_for_change("old", "", 0.05) == {
        "version": "old",
        "waiting": None,
    }


def test_serves_the_running_version(tmp_path: Path) -> None:
    server = start_server(
        ProjectHost(cache_dir=tmp_path / "cache"), "token", updates=UpdateNotice("v1")
    )
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/update",
            headers={"X-Blueprints-Token": "token"},
        )
        with urlopen(request, timeout=10) as response:
            body = json.loads(response.read())
    finally:
        server.shutdown()

    assert body == {"version": "v1", "waiting": None}


def test_relaunches_on_the_same_port_with_what_was_open() -> None:
    launch = Launch(8123, Path("/work/project"), "main...feature", watch=False)

    assert relaunch_arguments(launch) == [
        "/work/project",
        "--diff=main...feature",
        "--port=8123",
        "--no-open",
        "--no-watch",
    ]


def test_relaunches_to_the_start_screen_when_nothing_was_open() -> None:
    launch = Launch(8123, None, None, watch=True)

    assert relaunch_arguments(launch) == ["--port=8123", "--no-open"]


def make_installed(tmp_path: Path) -> Installed:
    origin = tmp_path / "origin.git"
    upstream = tmp_path / "upstream"
    folder = tmp_path / "install"
    upstream.mkdir()
    make_repository(upstream)
    make_files(upstream, FILES)
    git(upstream, "add", "-A")
    git(upstream, "commit", "-q", "-m", "first")
    git(tmp_path, "clone", "-q", "--bare", str(upstream), str(origin))
    git(upstream, "remote", "add", "origin", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(folder))
    make_repository(folder)
    notice = UpdateNotice(git(folder, "rev-parse", "HEAD").strip())
    restarts: list[str] = []
    updater = SelfUpdater(Checkout(folder), notice, lambda: restarts.append("restart"))
    return Installed(folder, upstream, notice, updater, restarts)


def make_repository(folder: Path) -> None:
    if not (folder / ".git").exists():
        git(folder, "init", "-q", "-b", "main")
    git(folder, "config", "user.email", "test@example.com")
    git(folder, "config", "user.name", "Test")
    git(folder, "config", "commit.gpgsign", "false")


def make_files(folder: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


def git(folder: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=folder, check=True, capture_output=True, text=True
    ).stdout
