import os
import subprocess
from pathlib import Path

INSTALL_FOLDER = Path(__file__).resolve().parents[2]
QUIET_GIT = {
    "GIT_TERMINAL_PROMPT": "0",
    "SSH_ASKPASS_REQUIRE": "never",
}


class CheckoutError(Exception):
    pass


class Checkout:
    def __init__(self, folder: Path = INSTALL_FOLDER) -> None:
        self.folder = folder.resolve()

    def is_repository_root(self) -> bool:
        try:
            top = self._run("rev-parse", "--show-toplevel")
        except CheckoutError:
            return False
        return Path(top.strip()).resolve() == self.folder

    def head(self) -> str:
        return self._run("rev-parse", "HEAD").strip()

    def branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD").strip()

    def has_local_changes(self) -> bool:
        return bool(self._run("status", "--porcelain", "--untracked-files=no").strip())

    def fetch(self, branch: str) -> str:
        remote = self._config(f"branch.{branch}.remote")
        merge = self._config(f"branch.{branch}.merge")
        self._run("fetch", "--quiet", "--no-tags", remote, merge)
        return self._run("rev-parse", "FETCH_HEAD").strip()

    def contains(self, ancestor: str, descendant: str) -> bool:
        return self._succeeds("merge-base", "--is-ancestor", ancestor, descendant)

    def changed_files(self, old: str, new: str) -> list[str]:
        output = self._run("diff", "--name-only", "-z", old, new)
        return [path for path in output.split("\0") if path]

    def fast_forward(self, commit: str) -> None:
        self._run("merge", "--ff-only", "--quiet", commit)

    def _config(self, key: str) -> str:
        try:
            return self._run("config", "--get", key).strip()
        except CheckoutError:
            raise CheckoutError(f"{key} is not set") from None

    def _succeeds(self, *arguments: str) -> bool:
        return self._git(*arguments).returncode == 0

    def _run(self, *arguments: str) -> str:
        completed = self._git(*arguments)
        if completed.returncode != 0:
            message = completed.stderr.decode("utf-8", "replace").strip()
            raise CheckoutError(message or "git failed")
        return completed.stdout.decode("utf-8", "replace")

    def _git(self, *arguments: str) -> "subprocess.CompletedProcess[bytes]":
        try:
            return subprocess.run(
                ["git", *arguments],
                cwd=self.folder,
                env={**os.environ, **QUIET_GIT},
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                timeout=120,
                start_new_session=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise CheckoutError(str(error)) from error
