import argparse
import secrets
import signal
import threading
import webbrowser
from pathlib import Path

from turtlemap.projects.git import GitError
from turtlemap.projects.registry import ServerRegistry
from turtlemap.projects.host import ProjectHost
from turtlemap.projects.recent import remember_project
from turtlemap.web.server import start_server


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    registry = ServerRegistry()
    host = ProjectHost(registry=registry)
    if args.folder:
        _open_folder(parser, host, Path(args.folder).expanduser(), args.diff)
    token = secrets.token_urlsafe(18)
    server = start_server(host, token, args.port)
    address = f"http://127.0.0.1:{server.server_address[1]}"
    url = f"{address}/?t={token}"
    registry.publish(address, host.agent_token)
    signal.signal(signal.SIGTERM, _stop)
    print(f"Turtlemap is running at {url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        registry.remove()
    server.shutdown()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="turtlemap",
        description="Browse a Python, JavaScript or TypeScript codebase as blueprint-style dependency maps and dataflow graphs.",
    )
    parser.add_argument("folder", nargs="?", help="project folder to open")
    parser.add_argument(
        "--diff",
        metavar="RANGE",
        help="tint what changed in a git range, e.g. develop..my-branch, develop...my-branch, or develop for your working copy",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="port for the local server (default: any free port)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="print the address instead of opening it in your browser",
    )
    return parser


def _open_folder(
    parser: argparse.ArgumentParser, host: ProjectHost, folder: Path, diff: str | None
) -> None:
    if not folder.is_dir():
        parser.error(f"not a folder: {folder}")
    try:
        host.open(folder, diff)
    except GitError as error:
        parser.error(str(error))
    remember_project(folder)


def _stop(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    raise SystemExit(main())
