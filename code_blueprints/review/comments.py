import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from code_blueprints.config import config_directory

USER = "user"
AGENT = "agent"
AGENT_STATES = frozenset({"seen", "working", "done"})
ANCHOR_VIEWS = frozenset({"map", "blueprint", "code"})
MAX_BODY = 20_000
MAX_ANCHOR = 20_000
MAX_NOTE = 200
MAX_EVENTS = 2_000
MAX_WAIT = 30.0


class CommentError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def comments_directory() -> Path:
    return config_directory() / "comments"


class CommentStore:
    def __init__(self, folder: Path | None = None) -> None:
        self._folder = folder or comments_directory()
        self._changed = threading.Condition(threading.Lock())
        self._books: dict[Path, dict[str, Any]] = {}

    def threads(self, root: Path) -> list[dict[str, Any]]:
        with self._changed:
            return [_copy(thread) for thread in self._book(root)["threads"]]

    def thread(self, root: Path, thread_id: str) -> dict[str, Any]:
        with self._changed:
            return _copy(self._find(self._book(root), thread_id))

    def cursor(self, root: Path) -> int:
        with self._changed:
            return int(self._book(root)["cursor"])

    def agent(self, root: Path) -> dict[str, Any]:
        with self._changed:
            return dict(self._book(root)["agent"])

    def create(self, root: Path, author: str, anchor: Any, body: Any) -> dict[str, Any]:
        text = _body(body)
        checked = _anchor(anchor)
        with self._changed:
            book = self._book(root)
            now = time.time()
            thread_id = f"c{book['next']}"
            book["next"] += 1
            thread: dict[str, Any] = {
                "id": thread_id,
                "anchor": checked,
                "messages": [_message(thread_id, 1, author, text, now)],
                "resolved": False,
                "created": now,
                "updated": now,
                "agent": _fresh_agent_state(author, now),
            }
            book["threads"].append(thread)
            self._record(book, "created", thread_id, author)
            self._save(root, book)
            return _copy(thread)

    def reply(
        self, root: Path, thread_id: str, author: str, body: Any
    ) -> dict[str, Any]:
        text = _body(body)
        with self._changed:
            book = self._book(root)
            thread = self._find(book, thread_id)
            now = time.time()
            messages = thread["messages"]
            messages.append(_message(thread_id, len(messages) + 1, author, text, now))
            thread["updated"] = now
            if author == USER:
                thread["agent"] = {"state": None, "note": None, "at": now}
            self._record(book, "replied", thread_id, author)
            self._save(root, book)
            return _copy(thread)

    def resolve(
        self, root: Path, thread_id: str, author: str, resolved: bool
    ) -> dict[str, Any]:
        if author != USER:
            raise CommentError("Only the person reviewing can resolve comments", 403)
        with self._changed:
            book = self._book(root)
            thread = self._find(book, thread_id)
            if thread["resolved"] != resolved:
                thread["resolved"] = resolved
                thread["updated"] = time.time()
                self._record(
                    book, "resolved" if resolved else "reopened", thread_id, author
                )
                self._save(root, book)
            return _copy(thread)

    def mark(
        self,
        root: Path,
        thread_ids: list[str],
        author: str,
        state: Any,
        note: Any = None,
    ) -> list[dict[str, Any]]:
        if author != AGENT:
            raise CommentError("Only an agent can set its own progress", 403)
        if state not in AGENT_STATES:
            raise CommentError(
                f"State must be one of {', '.join(sorted(AGENT_STATES))}"
            )
        with self._changed:
            book = self._book(root)
            threads = [self._find(book, thread_id) for thread_id in thread_ids]
            now = time.time()
            for thread in threads:
                thread["agent"] = {"state": state, "note": _note(note), "at": now}
                self._record(book, "agent", thread["id"], author)
            if state == "working":
                book["agent"] = {**book["agent"], "note": _note(note), "at": now}
            self._save(root, book)
            return [_copy(thread) for thread in threads]

    def set_status(self, root: Path, author: str, note: Any) -> dict[str, Any]:
        if author != AGENT:
            raise CommentError("Only an agent can set its status line", 403)
        with self._changed:
            book = self._book(root)
            book["agent"] = {**book["agent"], "note": _note(note), "at": time.time()}
            self._record(book, "status", None, author)
            self._save(root, book)
            return dict(book["agent"])

    def events(
        self, root: Path, since: int, wait: float, author: str
    ) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, min(wait, MAX_WAIT))
        with self._changed:
            book = self._book(root)
            if author == AGENT:
                book["agent"] = {**book["agent"], "polled": time.time()}
            while True:
                fresh = [event for event in book["events"] if event["seq"] > since]
                remaining = deadline - time.monotonic()
                if fresh or remaining <= 0:
                    break
                self._changed.wait(remaining)
                book = self._book(root)
            changed = {event["thread"] for event in fresh if event["thread"]}
            return {
                "cursor": book["cursor"],
                "events": fresh,
                "threads": [
                    _copy(thread)
                    for thread in book["threads"]
                    if thread["id"] in changed
                ],
                "agent": dict(book["agent"]),
            }

    def _book(self, root: Path) -> dict[str, Any]:
        key = root.resolve()
        if key not in self._books:
            self._books[key] = self._load(key)
        return self._books[key]

    def _find(self, book: dict[str, Any], thread_id: str) -> dict[str, Any]:
        threads: list[dict[str, Any]] = book["threads"]
        for thread in threads:
            if thread["id"] == thread_id:
                return thread
        raise CommentError(f"No comment {thread_id}", 404)

    def _record(
        self, book: dict[str, Any], kind: str, thread_id: str | None, author: str
    ) -> None:
        book["cursor"] += 1
        book["events"].append(
            {
                "seq": book["cursor"],
                "type": kind,
                "thread": thread_id,
                "author": author,
                "at": time.time(),
            }
        )
        del book["events"][:-MAX_EVENTS]
        self._changed.notify_all()

    def _file(self, root: Path) -> Path:
        key = hashlib.sha1(str(root).encode()).hexdigest()[:16]
        return self._folder / f"{key}.json"

    def _load(self, root: Path) -> dict[str, Any]:
        try:
            data = json.loads(self._file(root).read_text())
        except (OSError, ValueError):
            data = {}
        return {
            "root": str(root),
            "next": int(data.get("next", 1)),
            "cursor": int(data.get("cursor", 0)),
            "threads": list(data.get("threads", [])),
            "events": list(data.get("events", [])),
            "agent": dict(data.get("agent", {"note": None, "at": None})),
        }

    def _save(self, root: Path, book: dict[str, Any]) -> None:
        target = self._file(root.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(book))
        os.replace(temporary, target)


def _copy(thread: dict[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = json.loads(json.dumps(thread))
    return copied


def _message(
    thread_id: str, number: int, author: str, body: str, at: float
) -> dict[str, Any]:
    return {"id": f"{thread_id}.{number}", "author": author, "body": body, "at": at}


def _fresh_agent_state(author: str, at: float) -> dict[str, Any]:
    return {"state": "seen" if author == AGENT else None, "note": None, "at": at}


def _body(body: Any) -> str:
    if not isinstance(body, str) or not body.strip():
        raise CommentError("Write something first")
    if len(body) > MAX_BODY:
        raise CommentError("That comment is too long")
    return body.strip()


def _note(note: Any) -> str | None:
    if note is None:
        return None
    if not isinstance(note, str):
        raise CommentError("A status note must be text")
    return " ".join(note.split())[:MAX_NOTE] or None


def _anchor(anchor: Any) -> dict[str, Any]:
    if not isinstance(anchor, dict) or anchor.get("view") not in ANCHOR_VIEWS:
        raise CommentError(f"An anchor needs a view: {', '.join(sorted(ANCHOR_VIEWS))}")
    if len(json.dumps(anchor)) > MAX_ANCHOR:
        raise CommentError("That selection is too large to comment on")
    checked: dict[str, Any] = json.loads(json.dumps(anchor))
    return checked
