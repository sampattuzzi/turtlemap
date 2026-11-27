import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

TOKEN_VARIABLE = "TURTLEMAP_RELAUNCH_TOKEN"
AGENT_TOKEN_VARIABLE = "TURTLEMAP_RELAUNCH_AGENT_TOKEN"


@dataclass(frozen=True)
class Launch:
    port: int
    root: Path | None
    diff: str | None
    watch: bool
    host: str | None = None


@dataclass(frozen=True)
class InheritedTokens:
    user: str | None
    agent: str | None


def relaunch(launch: Launch, token: str, agent_token: str) -> NoReturn:
    environment = {
        **os.environ,
        TOKEN_VARIABLE: token,
        AGENT_TOKEN_VARIABLE: agent_token,
    }
    command = [sys.executable, "-P", "-m", "turtlemap.app", *relaunch_arguments(launch)]
    sys.stdout.flush()
    sys.stderr.flush()
    os.execve(sys.executable, command, environment)


def relaunch_arguments(launch: Launch) -> list[str]:
    arguments = [str(launch.root)] if launch.root is not None else []
    if launch.diff:
        arguments.append(f"--diff={launch.diff}")
    arguments += [f"--port={launch.port}", "--no-open"]
    if not launch.watch:
        arguments.append("--no-watch")
    if launch.host:
        arguments.append(f"--host={launch.host}")
    return arguments


def inherited_tokens() -> InheritedTokens:
    return InheritedTokens(
        os.environ.pop(TOKEN_VARIABLE, None),
        os.environ.pop(AGENT_TOKEN_VARIABLE, None),
    )
