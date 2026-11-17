import io
import threading
import time
from pathlib import Path

import pytest

from code_blueprints.agent import main
from tests.conftest import Running


@pytest.fixture
def agent_env(running: Running, monkeypatch: pytest.MonkeyPatch) -> Running:
    monkeypatch.setenv(
        "CODE_BLUEPRINTS_URL", f"http://127.0.0.1:{running.server.server_address[1]}"
    )
    monkeypatch.setenv("CODE_BLUEPRINTS_TOKEN", running.host.agent_token)
    return running


def make_comment(running: Running, body: str = "Why square it?") -> str:
    status, thread = running.call(
        "/api/comments",
        {"anchor": {"view": "map", "ids": ["m:shapes.py:Square.area"]}, "body": body},
    )
    assert status == 200
    return str(thread["id"])


def run_agent(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = main(list(argv), out)
    return code, out.getvalue()


def test_lists_open_comments_with_where_they_point(agent_env: Running) -> None:
    thread_id = make_comment(agent_env)

    code, text = run_agent("list")

    assert code == 0
    assert text.startswith(f"{thread_id} [open, agent:unseen]")
    assert "shapes.py:2-3 (Square.area)" in text
    assert '"Why square it?"' in text


def test_shows_the_code_behind_a_comment(agent_env: Running) -> None:
    thread_id = make_comment(agent_env)

    code, text = run_agent("show", thread_id)

    assert code == 0
    assert "      3          return side * side" in text
    assert "[user · " in text


def test_replies_and_reports_progress(agent_env: Running) -> None:
    thread_id = make_comment(agent_env)

    run_agent("working", thread_id, "--note", "updating shapes.py")
    run_agent("reply", thread_id, "Squaring keeps it positive.")
    status, listed = agent_env.call("/api/comments")

    thread = listed["threads"][0]
    assert [m["author"] for m in thread["messages"]] == ["user", "agent"]
    assert thread["agent"] == {
        "state": "working",
        "note": "updating shapes.py",
        "at": thread["agent"]["at"],
    }
    assert listed["agent"]["note"] == "updating shapes.py"


def test_has_no_way_to_resolve(agent_env: Running) -> None:
    with pytest.raises(SystemExit):
        run_agent("resolve", "c1")


def test_watch_starts_with_unseen_comments(agent_env: Running) -> None:
    thread_id = make_comment(agent_env)

    code, text = run_agent("watch", "--once")

    assert code == 0
    assert text.startswith(f"unseen: {thread_id} [open, agent:unseen]")
    assert text.rstrip().endswith(f"code-blueprints-agent show {thread_id}")


def test_watch_wakes_on_a_new_comment(agent_env: Running) -> None:
    results: list[str] = []
    watcher = threading.Thread(
        target=lambda: results.append(run_agent("watch", "--once")[1])
    )
    watcher.start()
    time.sleep(0.5)
    thread_id = make_comment(agent_env, "Is this right?")
    watcher.join(30)

    assert results and results[0].startswith(f"new comment: {thread_id}")


def test_watch_skips_comments_already_seen(agent_env: Running) -> None:
    first = make_comment(agent_env)
    run_agent("seen", first)
    results: list[str] = []
    watcher = threading.Thread(
        target=lambda: results.append(run_agent("watch", "--once")[1])
    )
    watcher.start()
    time.sleep(0.5)
    agent_env.call("/api/comments/reply", {"id": first, "body": "Any news?"})
    watcher.join(30)

    assert results[0].startswith(f"new reply: {first}")


def test_says_how_to_start_a_server_when_none_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CODE_BLUEPRINTS_URL", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    code, _ = run_agent("--root", str(tmp_path), "list")

    assert code == 1
    assert "code-blueprints <folder> --no-open" in capsys.readouterr().err


def test_queries_the_structure_as_text(agent_env: Running) -> None:
    code, text = run_agent("query", "describe", "Square")

    assert code == 0
    assert text.startswith("class shapes.py › Square")


def test_query_needs_the_right_number_of_names(agent_env: Running) -> None:
    assert run_agent("query", "coupling", "Square")[0] == 1
