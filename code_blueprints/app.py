import argparse
import secrets
import signal
import threading
import webbrowser
from pathlib import Path

from code_blueprints.git import GitError
from code_blueprints.registry import ServerRegistry
from code_blueprints.host import ProjectHost
from code_blueprints.recent import remember_project
from code_blueprints.server import start_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="code-blueprints",
        description="Browse a Python codebase as blueprint-style dependency maps and dataflow graphs.",
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
    args = parser.parse_args(argv)
    registry = ServerRegistry()
    host = ProjectHost(registry=registry)
    if args.folder:
        folder = Path(args.folder).expanduser()
        if not folder.is_dir():
            parser.error(f"not a folder: {folder}")
        try:
            host.open(folder, args.diff)
        except GitError as error:
            parser.error(str(error))
        remember_project(folder)
    token = secrets.token_urlsafe(18)
    server = start_server(host, token, args.port)
    address = f"http://127.0.0.1:{server.server_address[1]}"
    url = f"{address}/?t={token}"
    registry.publish(address, host.agent_token)
    signal.signal(signal.SIGTERM, _stop)
    print(f"Code Blueprints is running at {url}", flush=True)
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


def _stop(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    raise SystemExit(main())
