import io
import json
from typing import Any

import pytest

from turtlemap.mcp import main
from tests.conftest import Running


@pytest.fixture
def agent_env(running: Running, monkeypatch: pytest.MonkeyPatch) -> Running:
    monkeypatch.setenv(
        "TURTLEMAP_URL", f"http://127.0.0.1:{running.server.server_address[1]}"
    )
    monkeypatch.setenv("TURTLEMAP_TOKEN", running.host.agent_token)
    return running


def make_exchange(*messages: dict[str, Any]) -> list[dict[str, Any]]:
    stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    stdout = io.StringIO()
    assert main([], stdin, stdout) == 0
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def make_call(ident: int, tool: str, **arguments: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": ident,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }


def expect_text(response: dict[str, Any]) -> str:
    assert response["result"]["isError"] is False, response
    return str(response["result"]["content"][0]["text"])


def test_initializes_with_the_client_s_protocol_version() -> None:
    [response] = make_exchange(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    )

    assert response["result"]["protocolVersion"] == "2024-11-05"
    assert response["result"]["capabilities"] == {"tools": {}}


def test_lists_comment_and_structure_tools_but_no_resolve() -> None:
    [response] = make_exchange({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    names = {tool["name"] for tool in response["result"]["tools"]}
    assert {
        "comments_wait",
        "comment_reply",
        "comment_progress",
        "structure_coupling",
    } <= names
    assert not any("resolve" in name for name in names)


def test_waits_for_comments_then_replies_and_reports_progress(
    agent_env: Running,
) -> None:
    agent_env.call(
        "/api/comments",
        {
            "anchor": {"view": "map", "ids": ["cls:shapes.py:Square"]},
            "body": "Rename this",
        },
    )

    waited, progress, replied = make_exchange(
        make_call(1, "comments_wait", seconds=0),
        make_call(2, "comment_progress", ids=["c1"], state="working", note="renaming"),
        make_call(3, "comment_reply", id="c1", text="Renamed to Quad"),
    )

    assert expect_text(waited).startswith("unseen: c1 [open, agent:unseen]")
    assert 'agent:working "renaming"' in expect_text(progress)
    assert "last by agent" in expect_text(replied)


def test_answers_structure_questions(agent_env: Running) -> None:
    [response] = make_exchange(make_call(1, "structure_describe", name="Square"))

    assert expect_text(response).startswith("class shapes.py › Square")


def test_reports_tool_failures_as_tool_errors(agent_env: Running) -> None:
    missing, unknown = make_exchange(
        make_call(1, "comment_show"),
        make_call(2, "structure_describe", name="Circle"),
    )

    assert missing["result"]["isError"] is True
    assert "Nothing called 'Circle'" in unknown["result"]["content"][0]["text"]


def test_rejects_unknown_methods_and_bad_json() -> None:
    stdin = io.StringIO('{"jsonrpc": "2.0", "id": 4, "method": "sing"}\nnot json\n')
    stdout = io.StringIO()
    main([], stdin, stdout)

    first, second = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert first["error"]["code"] == -32601
    assert second["error"]["code"] == -32700
