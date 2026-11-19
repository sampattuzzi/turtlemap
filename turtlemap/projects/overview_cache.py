import gzip
import hashlib
import json
from pathlib import Path

from turtlemap.analysis.project import Project

CACHE_VERSION = "8"


class OverviewCache:
    def __init__(self, folder: Path) -> None:
        self._folder = folder

    def overview_bytes(self, project: Project) -> bytes:
        fingerprint = fingerprint_of(project)
        cached = self._read(project, fingerprint)
        if cached is not None:
            return cached
        overview = json.dumps(project.overview(), separators=(",", ":")).encode()
        data = gzip.compress(overview, 6)
        self._write(project, fingerprint, data)
        return data

    def _read(self, project: Project, fingerprint: str) -> bytes | None:
        data_file, meta_file = self._files(project)
        try:
            meta = json.loads(meta_file.read_text())
            if meta.get("fingerprint") != fingerprint:
                return None
            return data_file.read_bytes()
        except (OSError, ValueError):
            return None

    def _write(self, project: Project, fingerprint: str, data: bytes) -> None:
        data_file, meta_file = self._files(project)
        meta = {"fingerprint": fingerprint, "root": str(project.root)}
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            data_file.write_bytes(data)
            meta_file.write_text(json.dumps(meta))
        except OSError:
            pass

    def _files(self, project: Project) -> tuple[Path, Path]:
        key = hashlib.sha1(str(project.root).encode()).hexdigest()[:16]
        return self._folder / f"{key}.json.gz", self._folder / f"{key}.json.meta"


def fingerprint_of(project: Project) -> str:
    digest = hashlib.sha1(CACHE_VERSION.encode())
    for path in project.workspace.index.files:
        try:
            stat = (project.root / path).stat()
        except OSError:
            continue
        digest.update(f"{path}\0{stat.st_mtime_ns}\0{stat.st_size}\n".encode())
    return digest.hexdigest()
