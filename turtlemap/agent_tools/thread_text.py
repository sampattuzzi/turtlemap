import json
import time
from typing import Any

EXCERPT = 160


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


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    shortened = flat if len(flat) <= EXCERPT else flat[: EXCERPT - 1] + "…"
    return json.dumps(shortened, ensure_ascii=False)
