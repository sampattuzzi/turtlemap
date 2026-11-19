import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from code_blueprints.agent_tools.client import AgentClient, AgentError, connect
from code_blueprints.agent_tools.thread_text import describe_thread, thread_text

DEFAULT_PROTOCOL = "2025-06-18"
SERVER_INFO = {"name": "code-blueprints", "version": "0.1.0"}
WAIT_LIMIT = 25
INSTRUCTIONS = (
    "Turtlemap shows this project as a dependency map and dataflow blueprints, "
    "and the reviewer leaves comments on it. Call comments_wait to block until the "
    "reviewer says something, then comment_show, mark it working with a short note, do "
    "the work, reply, and mark it done. Only the reviewer resolves comments. The "
    "structure_* tools describe the code's packages, modules, classes and functions, "
    "their dependencies, cohesion and coupling."
)
EVENT_WORDS = {
    "created": "new comment",
    "replied": "new reply",
    "resolved": "resolved by the reviewer",
    "reopened": "reopened by the reviewer",
}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    properties: dict[str, Any]
    required: tuple[str, ...]
    run: Callable[["Session", dict[str, Any]], str]

    def listing(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.properties,
                "required": list(self.required),
            },
        }


class Session:
    def __init__(
        self, root: Path, connector: Callable[[Path], AgentClient] = connect
    ) -> None:
        self.root = root
        self.cursor: int | None = None
        self._connector = connector
        self._client: AgentClient | None = None

    def get(self, path: str, **query: Any) -> Any:
        return self._retry(lambda client: client.get(path, **query))

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._retry(lambda client: client.post(path, payload))

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, -32600, "Not a JSON-RPC 2.0 message")
        method, ident = message.get("method"), message.get("id")
        if ident is None:
            return None
        params = message.get("params") or {}
        if method == "initialize":
            return _result(
                ident,
                {
                    "protocolVersion": params.get("protocolVersion")
                    or DEFAULT_PROTOCOL,
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                    "instructions": INSTRUCTIONS,
                },
            )
        if method == "ping":
            return _result(ident, {})
        if method == "tools/list":
            return _result(ident, {"tools": [tool.listing() for tool in TOOLS]})
        if method == "tools/call":
            return _result(ident, self._call(params))
        return _error(ident, -32601, f"Unknown method {method!r}")

    def _call(self, params: dict[str, Any]) -> dict[str, Any]:
        tool = next((t for t in TOOLS if t.name == params.get("name")), None)
        if tool is None:
            return _text(f"No tool called {params.get('name')!r}", error=True)
        arguments = params.get("arguments") or {}
        missing = [key for key in tool.required if arguments.get(key) in (None, "")]
        if missing:
            return _text(f"{tool.name} needs {', '.join(missing)}", error=True)
        try:
            return _text(tool.run(self, arguments))
        except AgentError as error:
            return _text(str(error), error=True)
        except ConnectionError as error:
            return _text(f"Cannot reach the Turtlemap server ({error})", error=True)

    def _retry(self, send: Callable[[AgentClient], Any]) -> Any:
        if self._client is None:
            self._client = self._connector(self.root)
        try:
            return send(self._client)
        except ConnectionError:
            self._client = self._connector(self.root)
            return send(self._client)


def main(
    argv: list[str] | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="code-blueprints-mcp",
        description="MCP server (stdio) for Turtlemap comments and structure queries.",
    )
    parser.add_argument(
        "--root", default=".", help="project folder the server is showing"
    )
    args = parser.parse_args(argv)
    session = Session(Path(args.root).expanduser())
    source, sink = stdin or sys.stdin, stdout or sys.stdout
    for line in source:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response: dict[str, Any] | None = _error(None, -32700, "Not valid JSON")
        else:
            response = session.handle(message)
        if response is not None:
            sink.write(json.dumps(response) + "\n")
            sink.flush()
    return 0


def _wait(session: Session, arguments: dict[str, Any]) -> str:
    if session.cursor is None:
        listing = session.get("/api/comments")
        session.cursor = int(listing["cursor"])
        backlog = [
            t
            for t in listing["threads"]
            if not t["resolved"] and not (t["agent"] or {}).get("state")
        ]
        if backlog:
            return "\n".join(f"unseen: {describe_thread(t)}" for t in backlog)
    seconds = max(0, min(WAIT_LIMIT, int(arguments.get("seconds", WAIT_LIMIT))))
    answer = session.get("/api/comments/events", since=session.cursor, wait=seconds)
    session.cursor = int(answer["cursor"])
    threads = {t["id"]: t for t in answer["threads"]}
    lines = [
        f"{EVENT_WORDS[e['type']]}: {describe_thread(threads[e['thread']])}"
        for e in answer["events"]
        if e["author"] != "agent"
        and e["type"] in EVENT_WORDS
        and e.get("thread") in threads
    ]
    return (
        "\n".join(dict.fromkeys(lines))
        or f"Nothing new in {seconds}s. Call comments_wait again to keep listening."
    )


def _list(session: Session, arguments: dict[str, Any]) -> str:
    listing = session.get("/api/comments")
    threads = [
        t for t in listing["threads"] if arguments.get("all") or not t["resolved"]
    ]
    threads.sort(key=lambda t: (t["resolved"], -t["updated"]))
    return "\n".join(describe_thread(t) for t in threads) or "No open comments."


def _show(session: Session, arguments: dict[str, Any]) -> str:
    return thread_text(session.get("/api/comments/thread", id=arguments["id"]))


def _reply(session: Session, arguments: dict[str, Any]) -> str:
    thread = session.post(
        "/api/comments/reply", {"id": arguments["id"], "body": arguments["text"]}
    )
    return describe_thread(thread)


def _progress(session: Session, arguments: dict[str, Any]) -> str:
    ids = arguments["ids"]
    answer = session.post(
        "/api/comments/progress",
        {
            "ids": [ids] if isinstance(ids, str) else ids,
            "state": arguments["state"],
            "note": arguments.get("note"),
        },
    )
    return "\n".join(describe_thread(t) for t in answer["threads"])


def _status(session: Session, arguments: dict[str, Any]) -> str:
    agent = session.post("/api/agent/status", {"note": arguments.get("text") or None})
    return f"status: {agent.get('note') or '(cleared)'}"


def _query(what: str, *keys: str) -> Callable[[Session, dict[str, Any]], str]:
    def run(session: Session, arguments: dict[str, Any]) -> str:
        query = {
            key: arguments[key] for key in keys if arguments.get(key) not in (None, "")
        }
        if arguments.get("tests"):
            query["tests"] = 1
        return str(session.get(f"/api/query/{what}", **query)["text"])

    return run


def _result(ident: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def _error(ident: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}


def _text(text: str, error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": error}


_STRING = {"type": "string"}
_NAME = {
    "type": "string",
    "description": "an id such as mod:pkg/file.py or cls:pkg/file.py:Name, a path, a dotted module, or Class.method",
}

TOOLS = (
    Tool(
        "comments_wait",
        "Wait up to `seconds` (max 25) for the reviewer to comment, reply, resolve or reopen. The first call lists comments you have not looked at yet. Call it in a loop to keep listening.",
        {"seconds": {"type": "integer", "minimum": 0, "maximum": WAIT_LIMIT}},
        (),
        _wait,
    ),
    Tool(
        "comments_list",
        "List open comments (all=true to include resolved ones).",
        {"all": {"type": "boolean"}},
        (),
        _list,
    ),
    Tool(
        "comment_show",
        "Show a comment thread with the code it points at.",
        {"id": _STRING},
        ("id",),
        _show,
    ),
    Tool(
        "comment_reply",
        "Reply to a comment thread.",
        {"id": _STRING, "text": _STRING},
        ("id", "text"),
        _reply,
    ),
    Tool(
        "comment_progress",
        "Tell the reviewer you have seen comments, are working on them (with a short note such as 'updating plots.py'), or think they are done. Only the reviewer can resolve.",
        {
            "ids": {"type": "array", "items": _STRING},
            "state": {"type": "string", "enum": ["seen", "working", "done"]},
            "note": _STRING,
        },
        ("ids", "state"),
        _progress,
    ),
    Tool(
        "agent_status",
        "Set the one-line status the reviewer sees; leave text empty to clear it.",
        {"text": _STRING},
        (),
        _status,
    ),
    Tool(
        "structure_report",
        "Cohesion, coupling and instability for every module, the most coupled module pairs, any cycles, and the folders, files, classes and functions that are too large or complex.",
        {"tests": {"type": "boolean"}, "top": {"type": "integer", "minimum": 1}},
        (),
        _query("report", "top"),
    ),
    Tool(
        "structure_tree",
        "List the packages, modules, classes and functions under a name (or the project).",
        {"name": _NAME, "depth": {"type": "integer", "minimum": 1}},
        (),
        _query("tree", "name", "depth"),
    ),
    Tool(
        "structure_find",
        "Find ids by name.",
        {"text": _STRING},
        ("text",),
        _query("find", "text"),
    ),
    Tool(
        "structure_describe",
        "What a package, module, class or function contains, how large and complex it is, what it depends on and what uses it.",
        {"name": _NAME},
        ("name",),
        _query("describe", "name"),
    ),
    Tool(
        "structure_cohesion",
        "How cohesive a package, module, class or function is, with the groups it splits into.",
        {"name": _NAME},
        ("name",),
        _query("cohesion", "name"),
    ),
    Tool(
        "structure_coupling",
        "How tightly two parts depend on each other, in each direction.",
        {"a": _NAME, "b": _NAME},
        ("a", "b"),
        _query("coupling", "a", "b"),
    ),
    Tool(
        "structure_blueprint",
        "The dataflow blueprint of a function: its nodes, wires and order.",
        {"name": _NAME},
        ("name",),
        _query("blueprint", "name"),
    ),
)


if __name__ == "__main__":
    raise SystemExit(main())
