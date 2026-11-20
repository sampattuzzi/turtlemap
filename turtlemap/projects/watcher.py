import os
import threading
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from turtlemap.analysis.workspace.files import EXCLUDED_DIRECTORIES, is_source

CHANGES = frozenset({"created", "deleted", "modified", "moved"})
ALIAS_CONFIGS = ("tsconfig", "jsconfig")


class ProjectWatcher(FileSystemEventHandler):
    def __init__(self, on_change: Callable[[], None], delay: float = 0.3) -> None:
        self._on_change = on_change
        self._delay = delay
        self._root: Path | None = None
        self._observer: BaseObserver | None = None
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def watch(self, root: Path) -> None:
        root = root.resolve()
        with self._lock:
            if root == self._root:
                return
            self._stop_observing()
            self._root = root
            observer = Observer()
            observer.daemon = True
            observer.schedule(self, str(root), recursive=True)
            observer.start()
            self._observer = observer

    def stop(self) -> None:
        with self._lock:
            self._stop_observing()
            self._root = None

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type not in CHANGES:
            return
        if event.is_directory and event.event_type == "modified":
            return
        paths = [event.src_path, event.dest_path]
        if any(self._matters(path, event.is_directory) for path in paths if path):
            self._soon()

    def _matters(self, path: str | bytes, is_directory: bool) -> bool:
        root = self._root
        if root is None:
            return False
        try:
            relative = PurePosixPath(Path(os.fsdecode(path)).relative_to(root))
        except ValueError:
            return False
        if not relative.parts:
            return False
        folders = relative.parts if is_directory else relative.parts[:-1]
        if any(
            part.startswith(".") or part in EXCLUDED_DIRECTORIES for part in folders
        ):
            return False
        return (
            is_directory or is_source(relative.as_posix()) or _is_alias_config(relative)
        )

    def _soon(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, self._on_change)
            self._timer.daemon = True
            self._timer.start()

    def _stop_observing(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._observer is not None:
            self._observer.stop()
            self._observer = None


def _is_alias_config(path: PurePosixPath) -> bool:
    return path.name.startswith(ALIAS_CONFIGS) and path.suffix == ".json"
