import os
import subprocess
from pathlib import Path, PurePosixPath

from turtlemap.languages.registry import EXTENSIONS, language_for

EXCLUDED_DIRECTORIES = frozenset(
    {
        "node_modules",
        "__pycache__",
        "node_modules",
        "site-packages",
        "venv",
        "build",
        "dist",
        "dist-packages",
    }
)


def source_files_under(root: Path) -> list[str]:
    tracked = _git_source_files(root)
    if tracked is not None:
        return tracked
    found: list[str] = []
    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = [
            name for name in subdirectories if not is_ignored_folder(name)
        ]
        for filename in filenames:
            relative = Path(directory, filename).relative_to(root).as_posix()
            if is_source(relative):
                found.append(relative)
    return found


def is_ignored_folder(name: str) -> bool:
    return name.startswith(".") or name in EXCLUDED_DIRECTORIES


def is_source(path: str) -> bool:
    language = language_for(path)
    return language is not None and language.includes(path)


def _git_source_files(root: Path) -> list[str] | None:
    try:
        completed = subprocess.run(
            [
                "git",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                *(f"*{extension}" for extension in EXTENSIONS),
            ],
            cwd=root,
            capture_output=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    paths = [
        entry
        for entry in completed.stdout.decode("utf-8", "replace").split("\0")
        if entry
    ]
    return [
        path
        for path in paths
        if not _is_excluded(path) and is_source(path) and (root / path).is_file()
    ]


def _is_excluded(path: str) -> bool:
    return any(
        part in EXCLUDED_DIRECTORIES or part.startswith(".")
        for part in PurePosixPath(path).parts[:-1]
    )
