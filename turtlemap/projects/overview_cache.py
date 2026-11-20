import gzip
import hashlib
import json
import threading
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from turtlemap.analysis.project import Piece, Project
from turtlemap.analysis.workspace.parsed import MISSING, content_digest
from turtlemap.analysis.workspace.reads import SOURCE

CACHE_VERSION = "9"
CONFLICT = "conflict"

Stat = tuple[int, int, str]


@dataclass(frozen=True)
class Overview:
    data: bytes
    rebuilt: tuple[str, ...]
    changed: bool
    edited: tuple[str, ...] = ()


@dataclass
class ProjectState:
    files: tuple[str, ...]
    prints: dict[str, str]
    pieces: dict[str, Piece]
    data: bytes
    stats: dict[str, Stat] = field(default_factory=dict)
    saved: bool = False


class FileDigests:
    def __init__(self, root: Path, stats: dict[str, Stat]) -> None:
        self._root = root
        self.stats = dict(stats)

    def digest(self, path: str) -> str:
        try:
            stat = (self._root / path).stat()
        except OSError:
            return MISSING
        known = self.stats.get(path)
        if known is not None and known[:2] == (stat.st_mtime_ns, stat.st_size):
            return known[2]
        try:
            digest = content_digest((self._root / path).read_bytes())
        except OSError:
            return MISSING
        self.stats[path] = (stat.st_mtime_ns, stat.st_size, digest)
        return digest


class OverviewCache:
    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._states: dict[Path, ProjectState] = {}
        self._lock = threading.Lock()
        self._saving = threading.Lock()

    def overview(self, project: Project, previous: Project | None = None) -> Overview:
        with self._lock:
            started = time.perf_counter()
            state = self._states.get(project.root) or self._read(project)
            digests = FileDigests(project.root, state.stats if state else {})
            current = _Fingerprints(project, digests.digest)
            if previous is not None:
                _adopt_parses(project, previous, current)
            changed = _changed_keys(state, current) if state else set()
            kept = {
                path: piece
                for path, piece in (state.pieces if state else {}).items()
                if piece.keys.isdisjoint(changed)
            }
            files = project.workspace.index.files
            stale = [path for path in files if path not in kept]
            if state is not None and not stale and files == state.files:
                if digests.stats != state.stats:
                    state.stats, state.saved = digests.stats, False
                self._states = {project.root: state}
                return Overview(state.data, (), False)
            built = {piece.path: piece for piece in project.pieces(stale)}
            pieces = [kept.get(path) or built[path] for path in files]
            overview = project.assemble(pieces, time.perf_counter() - started)
            project.use_overview(overview)
            raw = json.dumps(overview, separators=(",", ":")).encode()
            for path, stamp in project.workspace.stamps().items():
                if stamp[2] != MISSING:
                    digests.stats.setdefault(path, stamp)
            seen = _Fingerprints(project, digests.digest)
            fresh = ProjectState(
                files,
                _prints(pieces, built, state.prints if state else {}, seen),
                {piece.path: piece for piece in pieces},
                gzip.compress(raw, 1),
                digests.stats,
            )
            self._states = {project.root: fresh}
            edited = _edited(changed, files, state.files if state else files)
            return Overview(fresh.data, tuple(stale), True, edited)

    def save(self, project: Project) -> None:
        with self._saving:
            with self._lock:
                state = self._states.get(project.root)
                if state is None or state.saved:
                    return
                state.saved = True
            self._write(project, state)

    def _read(self, project: Project) -> ProjectState | None:
        data_file, state_file = self._files(project)
        try:
            saved = json.loads(gzip.decompress(state_file.read_bytes()))
            if saved.get("version") != CACHE_VERSION:
                return None
            keys: list[str] = saved["keys"]
            return ProjectState(
                tuple(saved["files"]),
                dict(zip(keys, saved["prints"])),
                {
                    path: Piece.from_json(
                        path, entry, frozenset(keys[at] for at in entry["deps"])
                    )
                    for path, entry in saved["pieces"].items()
                },
                data_file.read_bytes(),
                {
                    path: (stat[0], stat[1], stat[2])
                    for path, stat in saved["stats"].items()
                },
                saved=True,
            )
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            IndexError,
            EOFError,
            zlib.error,
        ):
            return None

    def _write(self, project: Project, state: ProjectState) -> None:
        data_file, state_file = self._files(project)
        keys = sorted(state.prints)
        index = {key: at for at, key in enumerate(keys)}
        saved: dict[str, Any] = {
            "version": CACHE_VERSION,
            "root": str(project.root),
            "files": list(state.files),
            "keys": keys,
            "prints": [state.prints[key] for key in keys],
            "stats": {path: list(stat) for path, stat in state.stats.items()},
            "pieces": {
                path: {
                    **piece.to_json(),
                    "deps": sorted(index[key] for key in piece.keys),
                }
                for path, piece in state.pieces.items()
            },
        }
        encoded = gzip.compress(json.dumps(saved, separators=(",", ":")).encode(), 1)
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            _replace(data_file, state.data)
            _replace(state_file, encoded)
        except OSError:
            pass

    def _files(self, project: Project) -> tuple[Path, Path]:
        key = hashlib.sha1(str(project.root).encode()).hexdigest()[:16]
        return self._folder / f"{key}.json.gz", self._folder / f"{key}.state.gz"


def _replace(target: Path, data: bytes) -> None:
    partial = target.with_name(target.name + ".partial")
    partial.write_bytes(data)
    partial.replace(target)


class _Fingerprints:
    def __init__(self, project: Project, file_digest: Callable[[str], str]) -> None:
        self._project = project
        self._file_digest = file_digest
        self._known: dict[str, str | None] = {}

    def __call__(self, key: str) -> str | None:
        if key not in self._known:
            self._known[key] = self._project.workspace.fingerprint(
                key, self._file_digest
            )
        return self._known[key]


def _changed_keys(state: ProjectState, current: _Fingerprints) -> set[str]:
    return {key for key, value in state.prints.items() if current(key) != value}


def _edited(
    changed: set[str], files: tuple[str, ...], before: tuple[str, ...]
) -> tuple[str, ...]:
    sources = {key.removeprefix(SOURCE) for key in changed if key.startswith(SOURCE)}
    return tuple(sorted(sources | (set(files) ^ set(before))))


def _adopt_parses(project: Project, previous: Project, current: _Fingerprints) -> None:
    before = _Fingerprints(previous, lambda path: MISSING)
    project.workspace.adopt_parses(
        previous.workspace,
        lambda keys: all(before(key) == current(key) for key in keys),
    )


def _prints(
    pieces: list[Piece],
    built: dict[str, Piece],
    before: dict[str, str],
    seen: _Fingerprints,
) -> dict[str, str]:
    prints: dict[str, str] = {}
    for piece in pieces:
        for key in piece.keys:
            value = seen(key) if piece.path in built else before.get(key)
            if value is None or prints.get(key, value) != value:
                value = CONFLICT
            prints[key] = value
    return prints
