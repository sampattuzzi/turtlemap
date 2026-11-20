import os
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath

from turtlemap.analysis.workspace.parsed import module_name_for
from turtlemap.analysis.workspace.reads import ReadLog
from turtlemap.languages.aliases import PathAliases
from turtlemap.languages.registry import EXTENSIONS, language_for

_TYPESCRIPT_TWINS = {
    ".js": (".ts", ".tsx"),
    ".jsx": (".tsx",),
    ".mjs": (".mts",),
    ".cjs": (".cts",),
}


class ModuleIndex:
    def __init__(self, root: Path, files: Iterable[str], reads: ReadLog) -> None:
        self.files = tuple(sorted(set(files)))
        self._file_set = frozenset(self.files)
        self._reads = reads
        self._aliases = PathAliases(root, reads)
        suffixes: dict[tuple[str, str], list[str]] = {}
        packages: set[tuple[str, str]] = set()
        scripts: dict[tuple[str, str], list[str]] = {}
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
            folder = PurePosixPath(path).parent.as_posix()
            scripts.setdefault((name, folder), []).append(path)
        self._modules_by_suffix = suffixes
        self._packages_by_suffix = frozenset(packages)
        self._by_folder = {key: tuple(paths) for key, paths in scripts.items()}

    def contains(self, path: str) -> bool:
        self._reads.note(f"has:{path}")
        return path in self._file_set

    def find_module(self, dotted: str, *, near: str) -> str | None:
        language = _language_name(near)
        self._reads.note(f"mod:{language}:{dotted}")
        candidates = self._modules_by_suffix.get((language, dotted))
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
        language = _language_name(near)
        self._reads.note(f"pkg:{language}:{dotted}")
        return (language, dotted) in self._packages_by_suffix

    def files_beside(self, path: str) -> tuple[str, ...]:
        language = _language_name(path)
        folder = PurePosixPath(path).parent.as_posix()
        self._reads.note(f"dir:{language}:{folder}")
        return self._by_folder.get((language, folder), ())

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
                if self.contains(candidate):
                    return module_name_for(candidate)
        return None

    def fingerprint(self, key: str) -> str | None:
        kind, _, rest = key.partition(":")
        if kind == "has":
            return "1" if rest in self._file_set else "0"
        if kind == "aliases":
            return self._aliases.fingerprint(rest)
        language, _, name = rest.partition(":")
        if kind == "mod":
            return "|".join(self._modules_by_suffix.get((language, name), ()))
        if kind == "pkg":
            return "1" if (language, name) in self._packages_by_suffix else "0"
        if kind == "dir":
            return "|".join(self._by_folder.get((language, name), ()))
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
