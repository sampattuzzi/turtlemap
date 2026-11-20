import sys
import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

from turtlemap.updates.checkout import Checkout, CheckoutError

BRANCH = "main"
FIRST_CHECK = 10.0
CHECK_EVERY = 300.0
MAX_WAIT = 30.0
DEPENDENCY_FILES = frozenset({"pyproject.toml", "poetry.lock"})
SERVER_CODE = "turtlemap/"
BROWSER_CODE = "turtlemap/static/"


class Outcome(Enum):
    UP_TO_DATE = "up to date"
    SKIPPED = "skipped"
    UPDATED = "updated"
    RESTARTING = "restarting"
    NEEDS_INSTALL = "needs install"


class UpdateNotice:
    def __init__(self, version: str = "") -> None:
        self._version = version
        self._waiting = ""
        self._folder = ""
        self._changed = threading.Condition()

    def announce_version(self, version: str) -> None:
        with self._changed:
            self._version = version
            self._waiting = ""
            self._changed.notify_all()

    def announce_waiting(self, commit: str, folder: str) -> None:
        with self._changed:
            self._waiting, self._folder = commit, folder
            self._changed.notify_all()

    def state(self) -> dict[str, Any]:
        with self._changed:
            return self._state()

    def wait_for_change(
        self, version: str, waiting: str, wait: float
    ) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, min(wait, MAX_WAIT))
        with self._changed:
            while self._version == version and self._waiting == waiting:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._changed.wait(remaining)
            return self._state()

    def _state(self) -> dict[str, Any]:
        waiting = (
            {"commit": self._waiting, "folder": self._folder} if self._waiting else None
        )
        return {"version": self._version, "waiting": waiting}


class SelfUpdater:
    def __init__(
        self, checkout: Checkout, notice: UpdateNotice, restart: Callable[[], None]
    ) -> None:
        self._checkout = checkout
        self._notice = notice
        self._restart = restart
        self._stopped = threading.Event()

    def start(self, first: float = FIRST_CHECK, every: float = CHECK_EVERY) -> None:
        thread = threading.Thread(target=self._keep_checking, args=(first, every))
        thread.daemon = True
        thread.start()

    def stop(self) -> None:
        self._stopped.set()

    def check(self) -> Outcome:
        checkout = self._checkout
        if checkout.branch() != BRANCH:
            return Outcome.SKIPPED
        latest = checkout.fetch(BRANCH)
        head = checkout.head()
        if checkout.contains(latest, head):
            return Outcome.UP_TO_DATE
        if checkout.has_local_changes() or not checkout.contains(head, latest):
            return Outcome.SKIPPED
        changed = checkout.changed_files(head, latest)
        if any(path in DEPENDENCY_FILES for path in changed):
            self._notice.announce_waiting(latest, str(checkout.folder))
            return Outcome.NEEDS_INSTALL
        checkout.fast_forward(latest)
        if any(_is_server_code(path) for path in changed):
            self._restart()
            return Outcome.RESTARTING
        self._notice.announce_version(latest)
        return Outcome.UPDATED

    def _keep_checking(self, first: float, every: float) -> None:
        delay = first
        reported = ""
        while not self._stopped.wait(delay):
            delay = every
            try:
                outcome = self.check()
            except CheckoutError as error:
                if str(error) != reported:
                    reported = str(error)
                    print(
                        f"Could not check for a Turtlemap update: {error}",
                        file=sys.stderr,
                    )
                continue
            reported = ""
            if outcome is Outcome.RESTARTING:
                return


def own_updater(restart: Callable[[], None]) -> tuple[UpdateNotice, SelfUpdater | None]:
    checkout = Checkout()
    if not checkout.is_repository_root():
        return UpdateNotice(), None
    try:
        notice = UpdateNotice(checkout.head())
    except CheckoutError:
        return UpdateNotice(), None
    return notice, SelfUpdater(checkout, notice, restart)


def _is_server_code(path: str) -> bool:
    return path.startswith(SERVER_CODE) and not path.startswith(BROWSER_CODE)
