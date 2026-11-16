import io
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class GitError(Exception):
    pass


@dataclass(frozen=True)
class DiffRange:
    spec: str
    base: str
    head: str | None
    base_label: str
    head_label: str


@dataclass(frozen=True)
class FileChange:
    status: str
    path: str
    old_path: str | None = None


class Repository:
    def __init__(self, folder: Path) -> None:
        self.folder = folder.resolve()
        top = self._run("rev-parse", "--show-toplevel", cwd=self.folder).strip()
        self.top = Path(top).resolve()
        relative = self.folder.relative_to(self.top).as_posix()
        self.prefix = "" if relative == "." else relative

    def resolve_range(self, spec: str) -> DiffRange:
        text = spec.strip()
        if not text:
            raise GitError("Give a range such as develop..my-branch")
        if "..." in text:
            left, right = text.split("...", 1)
            head_label = right or "HEAD"
            head = self.sha(head_label)
            base = self._run("merge-base", self.sha(left or "HEAD"), head).strip()
            return DiffRange(
                text, base, head, f"merge base of {left or 'HEAD'}", head_label
            )
        if ".." in text:
            left, right = text.split("..", 1)
            if not right:
                return DiffRange(
                    text, self.sha(left or "HEAD"), None, left or "HEAD", "working copy"
                )
            return DiffRange(
                text, self.sha(left or "HEAD"), self.sha(right), left or "HEAD", right
            )
        return DiffRange(text, self.sha(text), None, text, "working copy")

    def sha(self, revision: str) -> str:
        try:
            return self._run(
                "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"
            ).strip()
        except GitError:
            raise GitError(f"Unknown revision: {revision}") from None

    def branches(self) -> list[str]:
        output = self._run(
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(refname:short)",
            "refs/heads",
            "refs/remotes",
        )
        return [
            line for line in output.splitlines() if line and not line.endswith("/HEAD")
        ]

    def changes(self, diff: DiffRange) -> list[FileChange]:
        arguments = ["diff", "--name-status", "-M", "-z", diff.base]
        if diff.head is not None:
            arguments.append(diff.head)
        arguments += ["--", self._pathspec()]
        fields = self._run(*arguments).split("\0")
        changes: list[FileChange] = []
        index = 0
        while index < len(fields) and fields[index]:
            status = fields[index][0]
            if status in "RC":
                old, new = self._local(fields[index + 1]), self._local(
                    fields[index + 2]
                )
                index += 3
                if new.endswith(".py"):
                    changes.append(
                        FileChange(
                            "added" if status == "C" else "modified",
                            new,
                            old if status == "R" else None,
                        )
                    )
                continue
            path = self._local(fields[index + 1])
            index += 2
            if path.endswith(".py"):
                changes.append(
                    FileChange(
                        {"A": "added", "D": "removed"}.get(status, "modified"), path
                    )
                )
        if diff.head is None:
            untracked = self._run(
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                "*.py",
                cwd=self.folder,
            )
            changes += [
                FileChange("added", path) for path in untracked.split("\0") if path
            ]
        return changes

    def extract(self, sha: str, destination: Path) -> list[str]:
        marker = destination / ".complete"
        if marker.exists():
            return marker.read_text().splitlines()
        destination.mkdir(parents=True, exist_ok=True)
        archive = subprocess.run(
            [
                "git",
                "archive",
                "--format=tar",
                sha,
                *([self.prefix] if self.prefix else []),
            ],
            cwd=self.top,
            capture_output=True,
            check=False,
        )
        if archive.returncode != 0:
            raise GitError(archive.stderr.decode("utf-8", "replace").strip())
        files: list[str] = []
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            for member in tar.getmembers():
                if not member.isfile() or not member.name.endswith(".py"):
                    continue
                local = self._local(member.name)
                if local.startswith("../") or PurePosixPath(local).is_absolute():
                    continue
                source = tar.extractfile(member)
                if source is None:
                    continue
                target = destination / local
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read())
                files.append(local)
        marker.write_text("\n".join(files))
        return files

    def _pathspec(self) -> str:
        return f":(top){self.prefix}" if self.prefix else ":(top)"

    def _local(self, path: str) -> str:
        if not self.prefix:
            return path
        return (
            PurePosixPath(path).relative_to(self.prefix).as_posix()
            if path.startswith(self.prefix + "/")
            else "../" + path
        )

    def _run(self, *arguments: str, cwd: Path | None = None) -> str:
        try:
            completed = subprocess.run(
                ["git", *arguments],
                cwd=cwd or self.top,
                capture_output=True,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise GitError(str(error)) from error
        if completed.returncode != 0:
            raise GitError(
                completed.stderr.decode("utf-8", "replace").strip() or "git failed"
            )
        return completed.stdout.decode("utf-8", "replace")
