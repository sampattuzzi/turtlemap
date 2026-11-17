import os
import secrets
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ParamSpec

from code_blueprints.analysis.diff import ProjectDiff
from code_blueprints.analysis.project import Project
from code_blueprints.comparison import build_diff, head_project
from code_blueprints.git import DiffRange, GitError, Repository
from code_blueprints.overview_cache import OverviewCache
from code_blueprints.registry import ServerRegistry


def cache_directory() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "code-blueprints"


@dataclass(frozen=True)
class Session:
    root: Path | None = None
    project: Project | None = None
    overview_bytes: bytes | None = None
    error: str | None = None
    loading: bool = False
    diff_spec: str | None = None
    diff: ProjectDiff | None = None
    diff_bytes: bytes | None = None
    diff_error: str | None = None

    def without_diff(self) -> "Session":
        return replace(
            self, diff_spec=None, diff=None, diff_bytes=None, diff_error=None
        )

    def status(self) -> dict[str, Any]:
        project = self.project
        diff = (
            {
                "spec": self.diff_spec,
                "ready": self.diff_bytes is not None,
                "error": self.diff_error,
            }
            if self.diff_spec
            else None
        )
        return {
            "open": project is not None,
            "root": str(project.display_root) if project else None,
            "name": project.name if project else None,
            "files": len(project.workspace.files) if project else 0,
            "loading": self.loading,
            "ready": self.overview_bytes is not None
            and (diff is None or diff["ready"]),
            "error": self.error or (diff["error"] if diff else None),
            "diff": diff,
        }


class ProjectHost:
    def __init__(
        self,
        cache_dir: Path | None = None,
        registry: ServerRegistry | None = None,
    ) -> None:
        cache_dir = cache_dir or cache_directory()
        self.agent_token = secrets.token_urlsafe(18)
        self._registry = registry
        self._overviews = OverviewCache(cache_dir)
        self._trees = cache_dir / "trees"
        self._lock = threading.Lock()
        self._session = Session()

    def open(self, root: Path, diff: str | None = None) -> None:
        if self._registry is not None:
            self._registry.set_root(root)
        if diff:
            resolved = root.resolve()
            self._begin(lambda current: replace(current.without_diff(), root=resolved))
            self.open_diff(diff)
            return
        project = Project(root)
        session = self._begin(
            lambda current: Session(root=root.resolve(), project=project, loading=True)
        )
        _in_background(self._load_overview, session, project)

    def open_diff(self, spec: str) -> None:
        root = self._session.root
        if root is None:
            raise GitError("Open a project before comparing revisions")
        repository = Repository(root)
        diff_range = repository.resolve_range(spec)
        session = self._begin(
            lambda current: replace(current.without_diff(), diff_spec=diff_range.spec)
        )
        _in_background(self._compare, session, root, repository, diff_range)

    def clear_diff(self) -> None:
        root = self._session.root
        if root is not None:
            self.open(root)

    def reload(self) -> None:
        session = self._session
        if session.root is None:
            return
        if session.diff_spec:
            self.open_diff(session.diff_spec)
        else:
            self.open(session.root)

    def status(self) -> dict[str, Any]:
        return self._session.status()

    def session(self) -> Session:
        return self._session

    def root(self) -> Path | None:
        return self._session.root

    def project(self) -> Project | None:
        return self._session.project

    def _begin(self, start: Callable[[Session], Session]) -> Session:
        with self._lock:
            self._session = start(self._session)
            return self._session

    def _advance(self, current: Session, after: Session) -> Session | None:
        with self._lock:
            if self._session is not current:
                return None
            self._session = after
            return after

    def _load_overview(self, session: Session, project: Project) -> Session | None:
        try:
            data = self._overviews.overview_bytes(project)
        except Exception:
            error = traceback.format_exc(limit=5)
            return self._advance(session, replace(session, error=error, loading=False))
        loaded = replace(session, overview_bytes=data, loading=False)
        return self._advance(session, loaded)

    def _compare(
        self,
        session: Session,
        root: Path,
        repository: Repository,
        diff_range: DiffRange,
    ) -> None:
        latest: Session | None = session
        try:
            head = head_project(repository, diff_range, root, self._trees)
            reading = replace(
                session, project=head, overview_bytes=None, error=None, loading=True
            )
            latest = self._advance(session, reading)
            if latest is not None:
                latest = self._load_overview(latest, head)
            if latest is not None:
                diff, data = build_diff(repository, diff_range, head, self._trees)
                self._advance(latest, replace(latest, diff=diff, diff_bytes=data))
        except Exception as error:
            if latest is not None:
                failed = replace(latest, diff_error=_describe(error))
                self._advance(latest, failed)


Arguments = ParamSpec("Arguments")


def _in_background(
    task: Callable[Arguments, object],
    *args: Arguments.args,
    **kwargs: Arguments.kwargs,
) -> None:
    threading.Thread(target=task, args=args, kwargs=kwargs, daemon=True).start()


def _describe(error: Exception) -> str:
    if isinstance(error, GitError):
        return str(error)
    return traceback.format_exc(limit=5)
