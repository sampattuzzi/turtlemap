import json
from pathlib import Path

from turtlemap.config import config_directory

REMEMBERED = 8


def config_file() -> Path:
    return config_directory() / "recent.json"


def recent_projects() -> list[str]:
    try:
        entries = json.loads(config_file().read_text())
    except (OSError, ValueError):
        return []
    return [
        entry for entry in entries if isinstance(entry, str) and Path(entry).is_dir()
    ][:REMEMBERED]


def remember_project(folder: Path) -> None:
    entries = [str(folder.resolve())] + [
        entry for entry in recent_projects() if entry != str(folder.resolve())
    ]
    try:
        config_file().parent.mkdir(parents=True, exist_ok=True)
        config_file().write_text(json.dumps(entries[:REMEMBERED]))
    except OSError:
        pass
