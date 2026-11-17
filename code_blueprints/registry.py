import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from code_blueprints.seen import config_directory


@dataclass(frozen=True)
class ServerInfo:
    url: str
    token: str
    root: str | None
    pid: int


def registry_directory() -> Path:
    return config_directory() / "servers"


class ServerRegistry:
    def __init__(self, folder: Path | None = None) -> None:
        self._folder = folder or registry_directory()
        self._lock = threading.Lock()
        self._url: str | None = None
        self._token: str | None = None
        self._root: str | None = None

    def publish(self, url: str, token: str) -> None:
        with self._lock:
            self._url, self._token = url, token
            self._write()

    def set_root(self, root: Path) -> None:
        with self._lock:
            self._root = str(root.resolve())
            self._write()

    def remove(self) -> None:
        with self._lock:
            self._url = None
            try:
                self._file().unlink()
            except OSError:
                pass

    def _file(self) -> Path:
        return self._folder / f"{os.getpid()}.json"

    def _write(self) -> None:
        if self._url is None or self._token is None:
            return
        self._folder.mkdir(parents=True, exist_ok=True)
        target = self._file()
        temporary = target.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(
                {
                    "url": self._url,
                    "token": self._token,
                    "root": self._root,
                    "pid": os.getpid(),
                },
                handle,
            )
        os.replace(temporary, target)


def find_server(near: Path, folder: Path | None = None) -> ServerInfo | None:
    explicit = os.environ.get("CODE_BLUEPRINTS_URL")
    if explicit:
        return ServerInfo(
            explicit.rstrip("/"), os.environ.get("CODE_BLUEPRINTS_TOKEN", ""), None, 0
        )
    running = [info for info in _registered(folder or registry_directory())]
    here = near.resolve()
    matching = [
        info
        for info in running
        if info.root is not None and _related(here, Path(info.root))
    ]
    if matching:
        return max(matching, key=lambda info: len(info.root or ""))
    return running[0] if len(running) == 1 else None


def _registered(folder: Path) -> list[ServerInfo]:
    found: list[ServerInfo] = []
    for file in sorted(folder.glob("*.json")):
        try:
            data = json.loads(file.read_text())
            info = ServerInfo(
                str(data["url"]), str(data["token"]), data.get("root"), int(data["pid"])
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if _alive(info.pid):
            found.append(info)
    return found


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _related(here: Path, root: Path) -> bool:
    return here == root or root in here.parents or here in root.parents
