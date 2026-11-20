import gc
import secrets
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ParamSpec

from turtlemap.analysis.diff.project_diff import ProjectDiff
from turtlemap.config import cache_directory
from turtlemap.analysis.project import Project
from turtlemap.projects.comparison import build_diff, head_project
from turtlemap.analysis.diff.revisions import DiffRange
from turtlemap.projects.git import GitError, Repository
from turtlemap.projects.overview_cache import OverviewCache
from turtlemap.projects.registry import ServerRegistry
from turtlemap.projects.watcher import ProjectWatcher

MAX_WAIT = 30.0
SHOWN_CHANGES = 50


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
    revision: int = 0
    edited: tuple[str, ...] = ()
    rebuilt: int = 0

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
            "files": len(project.workspace.index.files) if project else 0,
            "loading": self.loading,
            "ready": self.overview_bytes is not None
            and (diff is None or diff["ready"]),
            "error": self.error or (diff["error"] if diff else None),
            "diff": diff,
            "revision": self.revision,
            "edited": list(self.edited[:SHOWN_CHANGES]),
            "editedCount": len(self.edited),
            "rebuilt": self.rebuilt,
        }


class ProjectHost:
    def __init__(
        self,
        cache_dir: Path | None = None,
        registry: ServerRegistry | None = None,
        agent_token: str | None = None,
    ) -> None:
        cache_dir = cache_dir or cache_directory()
        self.agent_token = agent_token or secrets.token_urlsafe(18)
        self._registry = registry
        self._overviews = OverviewCache(cache_dir)
        self._trees = cache_dir / "trees"
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)
        self._refreshing = threading.Lock()
        self._session = Session()
        self._watcher: ProjectWatcher | None = None

    def watch_files(self) -> None:
        self._watcher = ProjectWatcher(self.refresh)
        root = self._session.root
        if root is not None:
            self._watch(root)

    def open(self, root: Path, diff: str | None = None) -> None:
        if self._registry is not None:
            self._registry.set_root(root)
        self._watch(root)
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
        elif session.overview_bytes is None:
            self.open(session.root)
        else:
            self.refresh()

    def refresh(self) -> None:
        with self._refreshing:
            session = self._session
            previous = session.project
            if session.diff_spec or session.overview_bytes is None or previous is None:
                return
            project = Project(previous.root)
            try:
                result = self._overviews.overview(project, previous)
            except Exception:
                traceback.print_exc(limit=5, file=sys.stderr)
                return
            if result.changed:
                after = replace(
                    session,
                    project=project,
                    overview_bytes=result.data,
                    edited=result.edited,
                    rebuilt=len(result.rebuilt),
                )
                self._advance(session, after)
            self._overviews.save(project)

    def wait_for_change(self, since: int, wait: float) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, min(wait, MAX_WAIT))
        with self._changed:
            while self._session.revision <= since:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._changed.wait(remaining)
            return self._session.status()

    def status(self) -> dict[str, Any]:
        return self._session.status()

    def session(self) -> Session:
        return self._session

    def root(self) -> Path | None:
        return self._session.root

    def project(self) -> Project | None:
        return self._session.project

    def _watch(self, root: Path) -> None:
        if self._watcher is None:
            return
        try:
            self._watcher.watch(root)
        except OSError:
            traceback.print_exc(limit=3, file=sys.stderr)

    def _begin(self, start: Callable[[Session], Session]) -> Session:
        with self._changed:
            return self._become(start(self._session))

    def _advance(self, current: Session, after: Session) -> Session | None:
        with self._changed:
            if self._session is not current:
                return None
            return self._become(after)

    def _become(self, session: Session) -> Session:
        self._session = replace(session, revision=self._session.revision + 1)
        self._changed.notify_all()
        return self._session

    def _load_overview(self, session: Session, project: Project) -> Session | None:
        try:
            data = self._overviews.overview(project).data
        except Exception:
            error = traceback.format_exc(limit=5)
            return self._advance(session, replace(session, error=error, loading=False))
        self._overviews.save(project)
        loaded = replace(session, overview_bytes=data, loading=False)
        after = self._advance(session, loaded)
        gc.freeze()
        return after

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
