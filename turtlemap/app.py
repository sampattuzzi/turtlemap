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
from turtlemap.updates.relaunch import Launch, inherited_tokens, relaunch
from turtlemap.updates.updater import own_updater, UpdateNotice
from turtlemap.web.server import start_server


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    tokens = inherited_tokens()
    registry = ServerRegistry()
    host = ProjectHost(registry=registry, agent_token=tokens.agent)
    if not args.no_watch:
        host.watch_files()
    if args.folder:
        _open_folder(parser, host, Path(args.folder).expanduser(), args.diff)
    token = tokens.user or secrets.token_urlsafe(18)
    restart = threading.Event()
    notice, updater = (
        (UpdateNotice(), None) if args.no_update else own_updater(restart.set)
    )
    server = start_server(host, token, args.port, updates=notice)
    port = server.server_address[1]
    address = f"http://127.0.0.1:{port}"
    url = f"{address}/?t={token}"
    registry.publish(address, host.agent_token)
    signal.signal(signal.SIGTERM, _stop)
    if tokens.user:
        print("Turtlemap updated itself and started again.", flush=True)
    print(f"Turtlemap is running at {url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if not args.no_open:
        webbrowser.open(url)
    if updater is not None:
        updater.start()
    try:
        restart.wait()
    except KeyboardInterrupt:
        restart.clear()
    finally:
        registry.remove()
    server.shutdown()
    if restart.is_set():
        server.server_close()
        session = host.session()
        launch = Launch(port, session.root, session.diff_spec, not args.no_watch)
        relaunch(launch, token, host.agent_token)
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
    parser.add_argument(
        "--no-watch",
        action="store_true",
        help="do not redraw the map when source files change",
    )
    parser.add_argument(
        "--no-update",
        action="store_true",
        help="do not update Turtlemap itself when main moves on GitHub",
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
