import gzip
import hashlib
import json
from pathlib import Path

from turtlemap.analysis.diff.project_diff import ProjectDiff
from turtlemap.analysis.project import Project
from turtlemap.analysis.diff.revisions import DiffRange
from turtlemap.projects.git import Repository


def head_project(
    repository: Repository, diff_range: DiffRange, root: Path, trees: Path
) -> Project:
    if diff_range.head_sha is None:
        return Project(root)
    folder = _tree_folder(trees, diff_range.head_sha, repository)
    return Project(
        folder,
        repository.extract(diff_range.head_sha, folder),
        name=f"{root.name} @ {diff_range.head_label}",
        display_root=root,
    )


def build_diff(
    repository: Repository, diff_range: DiffRange, head: Project, trees: Path
) -> tuple[ProjectDiff, bytes]:
    folder = _tree_folder(trees, diff_range.base_sha, repository)
    base = Project(folder, repository.extract(diff_range.base_sha, folder))
    diff = ProjectDiff(base, head, repository.changes(diff_range), diff_range)
    summary = json.dumps(diff.summary(), separators=(",", ":")).encode()
    return diff, gzip.compress(summary, 6)


def _tree_folder(trees: Path, sha: str, repository: Repository) -> Path:
    folder_key = hashlib.sha1(str(repository.folder).encode()).hexdigest()[:8]
    return trees / f"{sha}-{folder_key}"
