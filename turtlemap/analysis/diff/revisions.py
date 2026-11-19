from dataclasses import dataclass


@dataclass(frozen=True)
class DiffRange:
    spec: str
    base_sha: str
    head_sha: str | None
    base_label: str
    head_label: str


@dataclass(frozen=True)
class FileChange:
    status: str
    path: str
    old_path: str | None = None
