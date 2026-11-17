import json
import os
import re
from pathlib import Path, PurePosixPath

_COMMENTS = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.S)
_TRAILING_COMMAS = re.compile(r",(\s*[}\]])")

Alias = tuple[str, tuple[str, ...]]


class PathAliases:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._by_directory: dict[str, tuple[Alias, ...]] = {}

    def candidates(self, specifier: str, near: str) -> list[str]:
        found: list[str] = []
        directory = PurePosixPath(near).parent
        while True:
            for pattern, targets in self._aliases(directory.as_posix()):
                rest = _match(pattern, specifier)
                if rest is None:
                    continue
                found.extend(
                    _normal(directory / target.replace("*", rest)) for target in targets
                )
            if directory == directory.parent:
                break
            directory = directory.parent
        return found

    def _aliases(self, directory: str) -> tuple[Alias, ...]:
        cached = self._by_directory.get(directory)
        if cached is None:
            cached = _read_aliases(self.root / directory)
            self._by_directory[directory] = cached
        return cached


def _read_aliases(directory: Path) -> tuple[Alias, ...]:
    aliases: list[Alias] = []
    try:
        configs = sorted(directory.glob("tsconfig*.json")) + sorted(
            directory.glob("jsconfig*.json")
        )
    except OSError:
        return ()
    for config in configs:
        options = _compiler_options(config)
        paths = options.get("paths")
        if not isinstance(paths, dict):
            continue
        base = options.get("baseUrl")
        prefix = PurePosixPath(base) if isinstance(base, str) else PurePosixPath(".")
        for pattern, targets in paths.items():
            if isinstance(pattern, str) and isinstance(targets, list):
                aliases.append(
                    (
                        pattern,
                        tuple(
                            (prefix / target).as_posix()
                            for target in targets
                            if isinstance(target, str)
                        ),
                    )
                )
    return tuple(sorted(aliases, key=lambda alias: -len(alias[0])))


def _compiler_options(config: Path) -> dict[str, object]:
    try:
        text = config.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    text = _COMMENTS.sub(lambda found: found.group(1) or "", text)
    text = _TRAILING_COMMAS.sub(r"\1", text)
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    options = data.get("compilerOptions") if isinstance(data, dict) else None
    return options if isinstance(options, dict) else {}


def _match(pattern: str, specifier: str) -> str | None:
    if "*" not in pattern:
        return "" if pattern == specifier else None
    head, _, tail = pattern.partition("*")
    if (
        specifier.startswith(head)
        and specifier.endswith(tail)
        and len(specifier) >= len(head) + len(tail)
    ):
        return specifier[len(head) : len(specifier) - len(tail)]
    return None


def _normal(path: PurePosixPath) -> str:
    return os.path.normpath(path.as_posix()).replace(os.sep, "/")
