import argparse
import json
import sys
from pathlib import Path
from typing import Any

from turtlemap.agent_tools.client import connect

COMMENT_LIMIT = 140


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    root = parser.parse_args().root
    comments = json.load(sys.stdin)
    too_long = [
        comment["body"] for comment in comments if len(comment["body"]) > COMMENT_LIMIT
    ]
    if too_long:
        sys.exit(_too_long_message(too_long))
    client = connect(root)
    for comment in comments:
        thread = client.post("/api/comments", comment)
        print(thread["id"], _placement(thread), comment["body"])


def _too_long_message(bodies: list[str]) -> str:
    lines = [f"{len(body)} chars: {body}" for body in bodies]
    return f"Over {COMMENT_LIMIT} characters, nothing posted:\n" + "\n".join(lines)


def _placement(thread: dict[str, Any]) -> str:
    return "OUTDATED" if thread.get("where", {}).get("outdated") else "placed"


if __name__ == "__main__":
    main()
