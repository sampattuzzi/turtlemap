import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from code_blueprints.registry import ServerInfo, find_server

WATCH_WAIT = 25
RETRY_SECONDS = 2.0
EXCERPT = 160


class AgentError(Exception):
    pass


class AgentClient:
    def __init__(self, info: ServerInfo) -> None:
        self.info = info

    def get(self, path: str, **query: Any) -> Any:
        suffix = f"?{urlencode(query)}" if query else ""
        return self._send(Request(f"{self.info.url}{path}{suffix}"), timeout=60)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        request = Request(
            f"{self.info.url}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._send(request, timeout=30)

    def _send(self, request: Request, timeout: float) -> Any:
        request.add_header("X-Blueprints-Token", self.info.token)
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except HTTPError as error:
            try:
                message = json.loads(error.read()).get("error", str(error))
            except ValueError:
                message = str(error)
            raise AgentError(message) from None
        except (URLError, OSError) as error:
            raise ConnectionError(str(error)) from None


def connect(root: Path) -> AgentClient:
    info = find_server(root)
    if info is None:
        raise AgentError(
            f"No Code Blueprints server is running for {root}. "
            "Start one with: code-blueprints <folder> --no-open"
        )
    return AgentClient(info)


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


def describe_thread(thread: dict[str, Any]) -> str:
    agent = thread.get("agent") or {}
    state = agent.get("state") or "unseen"
    note = f' "{agent["note"]}"' if agent.get("note") else ""
    last = thread["messages"][-1]
    flags = [
        "resolved" if thread["resolved"] else "open",
        f"agent:{state}{note}",
    ]
    if thread.get("where", {}).get("outdated"):
        flags.append("outdated")
    return (
        f"{thread['id']} [{', '.join(flags)}] {anchor_label(thread)} · "
        f"{len(thread['messages'])} message(s), last by {last['author']}: "
        f"{_excerpt(last['body'])}"
    )


def anchor_label(thread: dict[str, Any]) -> str:
    anchor = thread.get("anchor", {})
    locations = thread.get("where", {}).get("locations", [])
    nodes: dict[str, list[str]] = {}
    for location in locations:
        names = nodes.setdefault(_place(location), [])
        if location.get("node"):
            names.append(repr(location["node"]))
    places = [
        (
            f"{where} node{'s' if len(names) > 1 else ''} {', '.join(names)}"
            if names
            else where
        )
        for where, names in list(nodes.items())[:3]
    ]
    if len(nodes) > 3:
        places.append(f"+{len(nodes) - 3} more")
    view = anchor.get("view", "?")
    return f"{view}: {', '.join(places) or anchor.get('label') or '?'}"


def thread_text(thread: dict[str, Any]) -> str:
    lines = [describe_thread(thread)]
    where = thread["where"]
    if where.get("outdated"):
        lines.append("The code this points at has changed since the comment was made.")
    for places in _same_source(where["locations"]):
        lines += [
            "",
            anchor_label({"anchor": thread["anchor"], "where": {"locations": places}}),
        ]
        lines += [
            f"  {number:>5}  {text}" for number, text in places[0].get("source") or []
        ]
    anchor = thread["anchor"]
    if anchor.get("text") and anchor.get("view") == "code":
        lines += ["", "Selected text when commented:"]
        lines += [f"         {line}" for line in str(anchor["text"]).splitlines()]
    lines.append("")
    for message in thread["messages"]:
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(message["at"]))
        lines += [f"[{message['author']} · {stamp}]", message["body"], ""]
    return "\n".join(lines)


def _place(location: dict[str, Any]) -> str:
    where = str(
        location.get("path") or location.get("folder") or location.get("library", "?")
    )
    if location.get("start"):
        where += f":{location['start']}"
        if location.get("end") and location["end"] != location["start"]:
            where += f"-{location['end']}"
    if location.get("qual"):
        where += f" ({location['qual']})"
    return where


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-blueprints-agent",
        description="Read and answer Code Blueprints review comments, and query the code map.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="project folder the server is showing (default: here)",
    )
    commands = parser.add_subparsers(required=True, metavar="command")

    def command(
        name: str, run: Callable[..., None], text: str
    ) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=text, description=text)
        sub.set_defaults(run=run)
        return sub

    watch = command(
        "watch",
        _watch,
        "Print one line per new comment, reply or resolution, starting with comments you have not seen. Runs until stopped.",
    )
    watch.add_argument("--once", action="store_true", help="exit after the first batch")
    watch.add_argument("--json", action="store_true", help="print JSON lines")
    listing = command("list", _list, "List comments, open ones first.")
    listing.add_argument("--all", action="store_true", help="include resolved comments")
    listing.add_argument("--json", action="store_true")
    show = command("show", _show, "Show a comment thread with the code it points at.")
    show.add_argument("id")
    show.add_argument("--json", action="store_true")
    reply = command(
        "reply", _reply, "Reply to a comment. Use - to read the text from stdin."
    )
    reply.add_argument("id")
    reply.add_argument("text")
    for name, text in (
        ("seen", "Mark comments as seen."),
        ("working", "Mark comments as being worked on."),
        ("done", "Mark comments as done, for the reviewer to resolve."),
    ):
        progress = command(name, _progress, text)
        progress.add_argument("ids", nargs="+")
        progress.add_argument("--note", help='short status, e.g. "updating plots.py"')
        progress.set_defaults(state=name)
    status = command(
        "status",
        _status,
        "Set the status line shown to the reviewer; omit text to clear it.",
    )
    status.add_argument("text", nargs="?")
    command("where", _where, "Show which server this folder talks to.")
    query = command(
        "query",
        _query,
        "Ask about the code's structure: report, tree [NAME], find TEXT, describe NAME, cohesion NAME, coupling A B, blueprint NAME. Names can be ids, paths, dotted modules or Class.method.",
    )
    query.add_argument("what", choices=sorted(_QUERY_ARGUMENTS))
    query.add_argument("names", nargs="*")
    query.add_argument("--depth", type=int, help="tree depth (default 2)")
    query.add_argument("--top", type=int, help="pairs to list in the report")
    query.add_argument(
        "--tests", action="store_true", help="count tests as dependants in the report"
    )
    query.add_argument("--json", action="store_true")
    return parser


def _watch(args: argparse.Namespace, root: Path, out: TextIO) -> None:
    printed: set[tuple[str, int, str]] = set()
    client: AgentClient | None = None
    cursor = 0
    lost = False
    while True:
        try:
            if client is None:
                client = connect(root)
                listing = client.get("/api/comments")
                cursor = listing["cursor"]
                backlog = [
                    thread
                    for thread in listing["threads"]
                    if not thread["resolved"]
                    and not (thread["agent"] or {}).get("state")
                ]
                if lost:
                    _emit(out, args, "reconnected", None, printed)
                    lost = False
                for thread in backlog:
                    _emit(out, args, "unseen", thread, printed)
                if backlog and args.once:
                    return
            answer = client.get("/api/comments/events", since=cursor, wait=WATCH_WAIT)
        except (ConnectionError, AgentError) as error:
            client = None
            if not lost:
                _emit(
                    out, args, f"server unreachable, retrying ({error})", None, printed
                )
                lost = True
            time.sleep(RETRY_SECONDS)
            continue
        cursor = answer["cursor"]
        threads = {thread["id"]: thread for thread in answer["threads"]}
        shown = 0
        for event in answer["events"]:
            if event["author"] == "agent" or event["type"] not in _EVENT_WORDS:
                continue
            thread = threads.get(event["thread"])
            if thread is not None:
                shown += _emit(out, args, _EVENT_WORDS[event["type"]], thread, printed)
        if shown and args.once:
            return


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


def _same_source(locations: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for location in locations:
        key = (
            location.get("path") or location.get("folder") or location.get("library"),
            location.get("start"),
            location.get("end"),
            location.get("source") is None,
        )
        groups.setdefault(key, []).append(location)
    return list(groups.values())


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


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    shortened = flat if len(flat) <= EXCERPT else flat[: EXCERPT - 1] + "…"
    return json.dumps(shortened, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
