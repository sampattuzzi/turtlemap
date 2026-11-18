import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from code_blueprints.projects.registry import ServerInfo, find_server


class AgentError(Exception):
    pass


class AgentClient:
    def __init__(self, info: ServerInfo) -> None:
        self.info = info

    def get(self, path: str, **query: Any) -> Any:
        suffix = f"?{urlencode(query)}" if query else ""
        return self._send(Request(f"{self.info.url}{path}{suffix}"), timeout=60)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        request = Request(
            f"{self.info.url}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._send(request, timeout=30)

    def _send(self, request: Request, timeout: float) -> Any:
        request.add_header("X-Blueprints-Token", self.info.token)
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except HTTPError as error:
            try:
                message = json.loads(error.read()).get("error", str(error))
            except ValueError:
                message = str(error)
            raise AgentError(message) from None
        except (URLError, OSError) as error:
            raise ConnectionError(str(error)) from None


def connect(root: Path) -> AgentClient:
    info = find_server(root)
    if info is None:
        raise AgentError(
            f"No Code Blueprints server is running for {root}. "
            "Start one with: code-blueprints <folder> --no-open"
        )
    return AgentClient(info)
