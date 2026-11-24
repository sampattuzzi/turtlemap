import gzip
import hashlib
import json
import threading
import time
import zlib
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from turtlemap.analysis.project import Piece, Project
from turtlemap.analysis.workspace.parsed import MISSING, content_digest
from turtlemap.analysis.workspace.reads import SOURCE

CACHE_VERSION = "11"
UNKNOWN = "unknown"
KEPT_VERSIONS = 3
KEPT_FOLDERS = 3
_READ_ERRORS = (
    OSError,
    ValueError,
    KeyError,
    TypeError,
    IndexError,
    EOFError,
    zlib.error,
)

Stat = tuple[int, int, str]
Fingerprint = Callable[[str], str | None]


class OverviewData:
    def __init__(self, source: Project | bytes) -> None:
        self._source = source
        self._lock = threading.Lock()

    def compressed(self) -> bytes:
        with self._lock:
            if isinstance(self._source, Project):
                overview = self._source.overview()
                raw = json.dumps(overview, separators=(",", ":")).encode()
                self._source = gzip.compress(raw, 1)
            return self._source


@dataclass(frozen=True)
class Overview:
    data: OverviewData
    pieces: Mapping[str, Piece]
    rebuilt: tuple[str, ...]
    changed: bool
    edited: tuple[str, ...] = ()


@dataclass(frozen=True)
class PieceVersion:
    id: str
    piece: Piece
    prints: Mapping[str, str]

    @classmethod
    def of(cls, piece: Piece, prints: Mapping[str, str]) -> "PieceVersion":
        return cls(_version_id(piece.path, prints), piece, prints)

    def differing(self, fingerprint: Fingerprint) -> set[str]:
        return {key for key, value in self.prints.items() if fingerprint(key) != value}

    def matches(self, fingerprint: Fingerprint) -> bool:
        return all(fingerprint(key) == value for key, value in self.prints.items())


class PieceStore:
    def __init__(self, versions: dict[str, list[PieceVersion]] | None = None) -> None:
        self._versions = versions or {}

    def get(self, path: str, version_id: str) -> PieceVersion | None:
        for version in self._versions.get(path, ()):
            if version.id == version_id:
                return version
        return None

    def find(self, path: str, fingerprint: Fingerprint) -> PieceVersion | None:
        for version in self._versions.get(path, ()):
            if version.matches(fingerprint):
                self.use(version)
                return version
        return None

    def add(self, piece: Piece, prints: Mapping[str, str]) -> PieceVersion:
        version = PieceVersion.of(piece, prints)
        self.use(version)
        return version

    def use(self, version: PieceVersion) -> None:
        others = [
            kept
            for kept in self._versions.get(version.piece.path, ())
            if kept.id != version.id
        ]
        self._versions[version.piece.path] = [version, *others][:KEPT_VERSIONS]

    def snapshot(self) -> dict[str, tuple[PieceVersion, ...]]:
        return {path: tuple(versions) for path, versions in self._versions.items()}


@dataclass(frozen=True)
class FolderView:
    files: tuple[str, ...]
    chosen: Mapping[str, str]
    stats: Mapping[str, Stat]
    data: OverviewData


@dataclass
class _Family:
    root: Path
    store: PieceStore
    views: dict[Path, FolderView] = field(default_factory=dict)
    unsaved_views: set[Path] = field(default_factory=set)
    store_saved: bool = True

    def remember(self, root: Path, view: FolderView) -> None:
        self.views.pop(root, None)
        self.views[root] = view
        for forgotten in list(self.views)[:-KEPT_FOLDERS]:
            del self.views[forgotten]
            self.unsaved_views.discard(forgotten)


class FileDigests:
    def __init__(self, root: Path, stats: Mapping[str, Stat]) -> None:
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
        self._family: _Family | None = None
        self._lock = threading.Lock()
        self._saving = threading.Lock()

    def overview(self, project: Project, previous: Project | None = None) -> Overview:
        with self._lock:
            started = time.perf_counter()
            family = self._family_of(project)
            view = family.views.get(project.root) or self._read_view(family, project)
            digests = FileDigests(project.root, view.stats if view else {})
            current = _Fingerprints(project, digests.digest)
            if previous is not None:
                _adopt_parses(project, previous, current)
            files = project.workspace.index.files
            kept, changed = _still_valid(family.store, view, current, set(files))
            if view is not None and files == view.files and len(kept) == len(files):
                for version in kept.values():
                    family.store.use(version)
                pieces = {path: kept[path].piece for path in files}
                project.use_pieces(list(pieces.values()), time.perf_counter() - started)
                if digests.stats != view.stats:
                    view = replace(view, stats=digests.stats)
                    family.unsaved_views.add(project.root)
                family.remember(project.root, view)
                return Overview(view.data, pieces, (), False)
            chosen = _choose(family.store, files, kept, current)
            stale = [path for path in files if path not in chosen]
            built = project.pieces(stale)
            for path, stamp in project.workspace.stamps().items():
                if stamp[2] != MISSING:
                    digests.stats.setdefault(path, stamp)
            seen = _Fingerprints(project, digests.digest)
            for piece in built:
                chosen[piece.path] = family.store.add(piece, _prints(piece, seen))
            if built:
                family.store_saved = False
            pieces = {path: chosen[path].piece for path in files}
            project.use_pieces(list(pieces.values()), time.perf_counter() - started)
            fresh = FolderView(
                files,
                {path: chosen[path].id for path in files},
                digests.stats,
                OverviewData(project),
            )
            family.unsaved_views.add(project.root)
            family.remember(project.root, fresh)
            before = view.chosen if view else {}
            rebuilt = tuple(
                path for path in files if before.get(path) != chosen[path].id
            )
            edited = _edited(changed, files, view.files if view else files)
            return Overview(fresh.data, pieces, rebuilt, True, edited)

    def pieces(self, project: Project, paths: Iterable[str]) -> dict[str, Piece]:
        with self._lock:
            family = self._family_of(project)
            view = family.views.get(project.root)
            digests = FileDigests(project.root, view.stats if view else {})
            current = _Fingerprints(project, digests.digest)
            wanted = [path for path in paths if project.workspace.index.contains(path)]
            found = {
                path: version.piece
                for path in wanted
                if (version := family.store.find(path, current)) is not None
            }
            built = project.pieces([path for path in wanted if path not in found])
            seen = _Fingerprints(project, digests.digest)
            for piece in built:
                found[piece.path] = family.store.add(piece, _prints(piece, seen)).piece
            if built:
                family.store_saved = False
            project.remember(found.values())
            return found

    def save(self) -> None:
        with self._saving:
            with self._lock:
                family = self._family
                if family is None:
                    return
                store = None if family.store_saved else family.store.snapshot()
                views = [(root, family.views[root]) for root in family.unsaved_views]
                family.store_saved = True
                family.unsaved_views.clear()
            self._write(family.root, store, views)

    def _family_of(self, project: Project) -> _Family:
        root = project.display_root.resolve()
        if self._family is None or self._family.root != root:
            self._family = _Family(root, self._read_store(root))
        return self._family

    def _read_store(self, root: Path) -> PieceStore:
        try:
            saved = _load(self._family_folder(root) / "pieces.gz")
            if saved.get("version") != CACHE_VERSION:
                return PieceStore()
            keys: list[str] = saved["keys"]
            values: list[str] = saved["values"]
            return PieceStore(
                {
                    path: [
                        _version_from_json(path, entry, keys, values)
                        for entry in entries
                    ]
                    for path, entries in saved["paths"].items()
                }
            )
        except _READ_ERRORS:
            return PieceStore()

    def _read_view(self, family: _Family, project: Project) -> FolderView | None:
        data_file, view_file = self._view_files(family.root, project.root)
        try:
            saved = _load(view_file)
            if saved.get("version") != CACHE_VERSION:
                return None
            files = tuple(saved["files"])
            return FolderView(
                files,
                dict(zip(files, saved["chosen"], strict=True)),
                {
                    path: (stat[0], stat[1], stat[2])
                    for path, stat in saved["stats"].items()
                },
                OverviewData(data_file.read_bytes()),
            )
        except _READ_ERRORS:
            return None

    def _write(
        self,
        family_root: Path,
        store: Mapping[str, Collection[PieceVersion]] | None,
        views: list[tuple[Path, FolderView]],
    ) -> None:
        try:
            self._family_folder(family_root).mkdir(parents=True, exist_ok=True)
            if store is not None:
                _replace(
                    self._family_folder(family_root) / "pieces.gz",
                    _dump(_store_to_json(family_root, store)),
                )
            for root, view in views:
                data_file, view_file = self._view_files(family_root, root)
                _replace(data_file, view.data.compressed())
                _replace(view_file, _dump(_view_to_json(root, view)))
            _remove_old_format(self._folder)
        except OSError:
            pass

    def _family_folder(self, root: Path) -> Path:
        return self._folder / _short_hash(str(root))

    def _view_files(self, family_root: Path, root: Path) -> tuple[Path, Path]:
        key = _short_hash(str(root))
        folder = self._family_folder(family_root)
        return folder / f"{key}.json.gz", folder / f"{key}.view.gz"


def _still_valid(
    store: PieceStore,
    view: FolderView | None,
    current: Fingerprint,
    files: set[str],
) -> tuple[dict[str, PieceVersion], set[str]]:
    kept: dict[str, PieceVersion] = {}
    changed: set[str] = set()
    for path, version_id in (view.chosen if view else {}).items():
        version = store.get(path, version_id)
        if version is None:
            continue
        differing = version.differing(current)
        changed |= differing
        if not differing and path in files:
            kept[path] = version
    return kept, changed


def _choose(
    store: PieceStore,
    files: Iterable[str],
    kept: Mapping[str, PieceVersion],
    current: Fingerprint,
) -> dict[str, PieceVersion]:
    chosen = dict(kept)
    for path in files:
        if path not in chosen:
            found = store.find(path, current)
            if found is not None:
                chosen[path] = found
    return chosen


def _prints(piece: Piece, seen: Fingerprint) -> dict[str, str]:
    prints: dict[str, str] = {}
    for key in piece.keys:
        value = seen(key)
        prints[key] = UNKNOWN if value is None else value
    return prints


def _version_id(path: str, prints: Mapping[str, str]) -> str:
    text = "\0".join([path, *(f"{key}\0{prints[key]}" for key in sorted(prints))])
    return hashlib.sha1(text.encode()).hexdigest()[:20]


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def _edited(
    changed: set[str], files: tuple[str, ...], before: tuple[str, ...]
) -> tuple[str, ...]:
    sources = {key.removeprefix(SOURCE) for key in changed if key.startswith(SOURCE)}
    return tuple(sorted(sources | (set(files) ^ set(before))))


def _adopt_parses(project: Project, previous: Project, current: Fingerprint) -> None:
    before = _Fingerprints(previous, lambda path: MISSING)
    project.workspace.adopt_parses(
        previous.workspace,
        lambda keys: all(before(key) == current(key) for key in keys),
    )


def _store_to_json(
    root: Path, store: Mapping[str, Collection[PieceVersion]]
) -> dict[str, Any]:
    keys = _Interned()
    values = _Interned()
    paths = {
        path: [
            {
                "id": version.id,
                "prints": [
                    index
                    for key in sorted(version.prints)
                    for index in (keys.index(key), values.index(version.prints[key]))
                ],
                **version.piece.to_json(),
            }
            for version in versions
        ]
        for path, versions in store.items()
    }
    return {
        "version": CACHE_VERSION,
        "root": str(root),
        "keys": keys.items,
        "values": values.items,
        "paths": paths,
    }


def _version_from_json(
    path: str, entry: dict[str, Any], keys: list[str], values: list[str]
) -> PieceVersion:
    flat: list[int] = entry["prints"]
    prints = {keys[flat[at]]: values[flat[at + 1]] for at in range(0, len(flat), 2)}
    piece = Piece.from_json(path, entry, frozenset(prints))
    return PieceVersion(entry["id"], piece, prints)


def _view_to_json(root: Path, view: FolderView) -> dict[str, Any]:
    return {
        "version": CACHE_VERSION,
        "root": str(root),
        "files": list(view.files),
        "chosen": [view.chosen[path] for path in view.files],
        "stats": {path: list(stat) for path, stat in view.stats.items()},
    }


def _load(file: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(gzip.decompress(file.read_bytes()))
    return loaded


def _dump(saved: dict[str, Any]) -> bytes:
    return gzip.compress(json.dumps(saved, separators=(",", ":")).encode(), 1)


def _replace(target: Path, data: bytes) -> None:
    partial = target.with_name(target.name + ".partial")
    partial.write_bytes(data)
    partial.replace(target)


def _remove_old_format(folder: Path) -> None:
    for old in [*folder.glob("*.state.gz"), *folder.glob("*.json.gz")]:
        old.unlink(missing_ok=True)


class _Interned:
    def __init__(self) -> None:
        self.items: list[str] = []
        self._at: dict[str, int] = {}

    def index(self, item: str) -> int:
        at = self._at.get(item)
        if at is None:
            at = self._at[item] = len(self.items)
            self.items.append(item)
        return at


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
