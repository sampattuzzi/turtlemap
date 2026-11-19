import os
from pathlib import Path

NAME = "turtlemap"
FORMER_NAME = "code-blueprints"


def config_directory() -> Path:
    return _named_directory("XDG_CONFIG_HOME", ".config")


def cache_directory() -> Path:
    return _named_directory("XDG_CACHE_HOME", ".cache")


def _named_directory(variable: str, fallback: str) -> Path:
    base = Path(os.environ.get(variable) or Path.home() / fallback)
    current = base / NAME
    former = base / FORMER_NAME
    if former.is_dir() and not current.exists():
        try:
            former.rename(current)
        except OSError:
            return former
    return current
