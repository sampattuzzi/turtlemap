import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, TextIO

from code_blueprints.agent_tools.client import AgentClient, AgentError, connect
from code_blueprints.agent_tools.thread_text import describe_thread, thread_text

WATCH_WAIT = 25
RETRY_SECONDS = 2.0


def main(argv: list[str] | None = None, out: TextIO | None = None) -> int:
    stream = out or sys.stdout
    args = _parser().parse_args(argv)
    root = Path(args.root).expanduser()
    try:
        command: Callable[[argparse.Namespace, Path, TextIO], None] = args.run
        command(args, root, stream)
    except AgentError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ConnectionError as error:
        print(f"error: cannot reach the server ({error})", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-blueprints-agent",
        description="Read and answer Turtlemap review comments, and query the code map.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="project folder the server is showing (default: here)",
    )
    commands = parser.add_subparsers(required=True, metavar="command")
    for command in _commands():
        sub = commands.add_parser(
            command.name, help=command.text, description=command.text
        )
        sub.set_defaults(run=command.run)
        command.arguments(sub)
    return parser


_Run = Callable[[argparse.Namespace, Path, TextIO], None]
_Arguments = Callable[[argparse.ArgumentParser], None]


@dataclass(frozen=True)
class _Command:
    name: str
    run: _Run
    text: str
    arguments: _Arguments


def _commands() -> list[_Command]:
    return [
        _Command(
            "watch",
            _watch,
            "Print one line per new comment, reply or resolution, starting with comments you have not seen. Runs until stopped.",
            _watch_arguments,
        ),
        _Command("list", _list, "List comments, open ones first.", _list_arguments),
        _Command(
            "show",
            _show,
            "Show a comment thread with the code it points at.",
            _show_arguments,
        ),
        _Command(
            "reply",
            _reply,
            "Reply to a comment. Use - to read the text from stdin.",
            _reply_arguments,
        ),
        *(
            _Command(state, _progress, text, partial(_progress_arguments, state=state))
            for state, text in _PROGRESS_STATES
        ),
        _Command(
            "status",
            _status,
            "Set the status line shown to the reviewer; omit text to clear it.",
            _status_arguments,
        ),
        _Command(
            "where", _where, "Show which server this folder talks to.", _no_arguments
        ),
        _Command(
            "query",
            _query,
            "Ask about the code's structure: report, tree [NAME], find TEXT, describe NAME, cohesion NAME, coupling A B, blueprint NAME. Names can be ids, paths, dotted modules or Class.method.",
            _query_arguments,
        ),
    ]


_PROGRESS_STATES = (
    ("seen", "Mark comments as seen."),
    ("working", "Mark comments as being worked on."),
    ("done", "Mark comments as done, for the reviewer to resolve."),
)


def _watch_arguments(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--once", action="store_true", help="exit after the first batch")
    sub.add_argument("--json", action="store_true", help="print JSON lines")


def _list_arguments(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--all", action="store_true", help="include resolved comments")
    sub.add_argument("--json", action="store_true")


def _show_arguments(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("id")
    sub.add_argument("--json", action="store_true")


def _reply_arguments(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("id")
    sub.add_argument("text")


def _progress_arguments(sub: argparse.ArgumentParser, state: str) -> None:
    sub.add_argument("ids", nargs="+")
    sub.add_argument("--note", help='short status, e.g. "updating plots.py"')
    sub.set_defaults(state=state)


def _status_arguments(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("text", nargs="?")


def _no_arguments(sub: argparse.ArgumentParser) -> None:
    pass


def _query_arguments(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("what", choices=sorted(_QUERY_ARGUMENTS))
    sub.add_argument("names", nargs="*")
    sub.add_argument("--depth", type=int, help="tree depth (default 2)")
    sub.add_argument("--top", type=int, help="pairs to list in the report")
    sub.add_argument(
        "--tests", action="store_true", help="count tests as dependants in the report"
    )
    sub.add_argument("--json", action="store_true")


def _watch(args: argparse.Namespace, root: Path, out: TextIO) -> None:
    _Watcher(args, root, out).run()


class _Watcher:
    def __init__(self, args: argparse.Namespace, root: Path, out: TextIO) -> None:
        self.args = args
        self.root = root
        self.out = out
        self.printed: set[tuple[str, int, str]] = set()
        self.client: AgentClient | None = None
        self.cursor = 0
        self.lost = False

    def run(self) -> None:
        while True:
            try:
                answer = self._next_answer()
            except (ConnectionError, AgentError) as error:
                self._lose(error)
                continue
            if answer is None or (self._report(answer) and self.args.once):
                return

    def _next_answer(self) -> dict[str, Any] | None:
        if self.client is None:
            self.client = connect(self.root)
            if self._catch_up(self.client) and self.args.once:
                return None
        answer: dict[str, Any] = self.client.get(
            "/api/comments/events", since=self.cursor, wait=WATCH_WAIT
        )
        return answer

    def _catch_up(self, client: AgentClient) -> bool:
        listing = client.get("/api/comments")
        self.cursor = listing["cursor"]
        backlog = [
            thread
            for thread in listing["threads"]
            if not thread["resolved"] and not (thread["agent"] or {}).get("state")
        ]
        if self.lost:
            self._emit("reconnected", None)
            self.lost = False
        for thread in backlog:
            self._emit("unseen", thread)
        return bool(backlog)

    def _lose(self, error: Exception) -> None:
        self.client = None
        if not self.lost:
            self._emit(f"server unreachable, retrying ({error})", None)
            self.lost = True
        time.sleep(RETRY_SECONDS)

    def _report(self, answer: dict[str, Any]) -> int:
        self.cursor = answer["cursor"]
        threads = {thread["id"]: thread for thread in answer["threads"]}
        shown = 0
        for event in answer["events"]:
            if event["author"] == "agent" or event["type"] not in _EVENT_WORDS:
                continue
            thread = threads.get(event["thread"])
            if thread is not None:
                shown += self._emit(_EVENT_WORDS[event["type"]], thread)
        return shown

    def _emit(self, word: str, thread: dict[str, Any] | None) -> int:
        return _emit(self.out, self.args, word, thread, self.printed)


_EVENT_WORDS = {
    "created": "new comment",
    "replied": "new reply",
    "resolved": "resolved by the reviewer",
    "reopened": "reopened by the reviewer",
}


def _emit(
    out: TextIO,
    args: argparse.Namespace,
    word: str,
    thread: dict[str, Any] | None,
    printed: set[tuple[str, int, str]],
) -> int:
    if thread is None:
        print(json.dumps({"event": word}) if args.json else word, file=out, flush=True)
        return 1
    key = (
        thread["id"],
        len(thread["messages"]),
        word if "resolv" in word or "reopen" in word else "",
    )
    if key in printed:
        return 0
    printed.add(key)
    if args.json:
        print(json.dumps({"event": word, "thread": thread}), file=out, flush=True)
    else:
        print(
            f"{word}: {describe_thread(thread)} → code-blueprints-agent show {thread['id']}",
            file=out,
            flush=True,
        )
    return 1


def _list(args: argparse.Namespace, root: Path, out: TextIO) -> None:
    listing = connect(root).get("/api/comments")
    threads = [t for t in listing["threads"] if args.all or not t["resolved"]]
    threads.sort(key=lambda t: (t["resolved"], -t["updated"]))
    if args.json:
        print(json.dumps(threads, indent=1), file=out)
        return
    for thread in threads:
        print(describe_thread(thread), file=out)
    if not threads:
        print("No open comments.", file=out)


def _show(args: argparse.Namespace, root: Path, out: TextIO) -> None:
    thread = connect(root).get("/api/comments/thread", id=args.id)
    print(json.dumps(thread, indent=1) if args.json else thread_text(thread), file=out)


def _reply(args: argparse.Namespace, root: Path, out: TextIO) -> None:
    text = sys.stdin.read() if args.text == "-" else args.text
    thread = connect(root).post("/api/comments/reply", {"id": args.id, "body": text})
    print(describe_thread(thread), file=out)


def _progress(args: argparse.Namespace, root: Path, out: TextIO) -> None:
    answer = connect(root).post(
        "/api/comments/progress",
        {"ids": args.ids, "state": args.state, "note": args.note},
    )
    for thread in answer["threads"]:
        print(describe_thread(thread), file=out)


def _status(args: argparse.Namespace, root: Path, out: TextIO) -> None:
    agent = connect(root).post("/api/agent/status", {"note": args.text})
    print(f"status: {agent.get('note') or '(cleared)'}", file=out)


def _where(args: argparse.Namespace, root: Path, out: TextIO) -> None:
    client = connect(root)
    status = client.get("/api/status")
    print(f"server: {client.info.url}", file=out)
    print(f"showing: {status.get('root')}", file=out)
    if status.get("diff"):
        print(f"comparing: {status['diff']['spec']}", file=out)


_QUERY_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "report": (),
    "tree": ("name",),
    "find": ("text",),
    "describe": ("name",),
    "cohesion": ("name",),
    "coupling": ("a", "b"),
    "blueprint": ("name",),
}


def _query(args: argparse.Namespace, root: Path, out: TextIO) -> None:
    wanted = _QUERY_ARGUMENTS[args.what]
    optional = args.what == "tree"
    if len(args.names) > len(wanted) or (
        not optional and len(args.names) < len(wanted)
    ):
        raise AgentError(
            f"query {args.what} takes {' '.join(w.upper() for w in wanted) or 'no names'}"
        )
    params: dict[str, Any] = dict(zip(wanted, args.names))
    for option in ("depth", "top"):
        if getattr(args, option) is not None:
            params[option] = getattr(args, option)
    if args.tests:
        params["tests"] = 1
    answer = connect(root).get(f"/api/query/{args.what}", **params)
    print(json.dumps(answer, indent=1) if args.json else answer["text"], file=out)


if __name__ == "__main__":
    raise SystemExit(main())
