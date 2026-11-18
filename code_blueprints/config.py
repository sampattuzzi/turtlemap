import os
from pathlib import Path


def config_directory() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "code-blueprints"
