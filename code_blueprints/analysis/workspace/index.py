import os
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath

from code_blueprints.analysis.workspace.parsed import module_name_for
from code_blueprints.languages.aliases import PathAliases
from code_blueprints.languages.registry import EXTENSIONS, language_for

_TYPESCRIPT_TWINS = {
    ".js": (".ts", ".tsx"),
    ".jsx": (".tsx",),
    ".mjs": (".mts",),
    ".cjs": (".cts",),
}


class ModuleIndex:
    def __init__(self, root: Path, files: Iterable[str]) -> None:
        self.files = tuple(sorted(set(files)))
        self._file_set = frozenset(self.files)
        self._aliases = PathAliases(root)
        suffixes: dict[tuple[str, str], list[str]] = {}
        packages: set[tuple[str, str]] = set()
        for path in self.files:
            parts = module_name_for(path).split(".")
            language = language_for(path)
            name = _language_name(path)
            for start in range(len(parts)):
                suffixes.setdefault((name, ".".join(parts[start:])), []).append(path)
            is_init = language is not None and language.is_package_init(path)
            directory = parts if is_init else parts[:-1]
            for start in range(len(directory)):
                for end in range(start + 1, len(directory) + 1):
                    packages.add((name, ".".join(directory[start:end])))
        self._modules_by_suffix = suffixes
        self._packages_by_suffix = frozenset(packages)

    def contains(self, path: str) -> bool:
        return path in self._file_set

    def find_module(self, dotted: str, *, near: str) -> str | None:
        candidates = self._modules_by_suffix.get((_language_name(near), dotted))
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        near_parts = PurePosixPath(near).parts
        return max(
            candidates,
            key=lambda candidate: (
                _shared_prefix(PurePosixPath(candidate).parts, near_parts),
                -len(candidate),
            ),
        )

    def is_package(self, dotted: str, *, near: str) -> bool:
        return (_language_name(near), dotted) in self._packages_by_suffix

    def locate(self, specifier: str, near: str) -> str | None:
        if specifier.startswith("."):
            target = PurePosixPath(near).parent / specifier
            bases = [os.path.normpath(target.as_posix()).replace(os.sep, "/")]
        else:
            bases = self._aliases.candidates(specifier, near)
        for normal in bases:
            if normal.startswith(".."):
                continue
            for candidate in (
                normal,
                *(normal + ext for ext in EXTENSIONS),
                *(f"{normal}/index{ext}" for ext in EXTENSIONS),
                *_typescript_sources(normal),
            ):
                if candidate in self._file_set:
                    return module_name_for(candidate)
        return None


def _language_name(path: str) -> str:
    language = language_for(path)
    return language.name if language is not None else ""


def _shared_prefix(left: Sequence[str], right: Sequence[str]) -> int:
    count = 0
    for left_part, right_part in zip(left, right):
        if left_part != right_part:
            break
        count += 1
    return count


def _typescript_sources(path: str) -> list[str]:
    suffix = PurePosixPath(path).suffix
    stem = path[: -len(suffix)] if suffix else path
    return [stem + twin for twin in _TYPESCRIPT_TWINS.get(suffix, ())]
