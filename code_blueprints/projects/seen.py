import hashlib
import json
import os
import threading
from pathlib import Path

from code_blueprints.config import config_directory


def state_directory() -> Path:
    return config_directory() / "seen"


class SeenStore:
    def __init__(self, folder: Path | None = None) -> None:
        self._folder = folder or state_directory()
        self._lock = threading.Lock()

    def load(self, root: Path) -> set[str]:
        with self._lock:
            return self._read(root)

    def update(self, root: Path, add: list[str], remove: list[str]) -> set[str]:
        with self._lock:
            seen = (self._read(root) | set(add)) - set(remove)
            self._write(root, seen)
            return seen

    def _file(self, root: Path) -> Path:
        key = hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:16]
        return self._folder / f"{key}.json"

    def _read(self, root: Path) -> set[str]:
        try:
            data = json.loads(self._file(root).read_text())
        except (OSError, ValueError):
            return set()
        entries = data.get("seen") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            return set()
        return {entry for entry in entries if isinstance(entry, str)}

    def _write(self, root: Path, seen: set[str]) -> None:
        target = self._file(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"root": str(root.resolve()), "seen": sorted(seen)})
        )
        os.replace(temporary, target)
