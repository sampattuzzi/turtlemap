import mimetypes
from pathlib import Path

from code_blueprints.web.framework import (
    Request,
    Response,
    error_response,
)


class StaticFiles:
    def __init__(self, folder: Path) -> None:
        self._folder = folder.resolve()

    def serve(self, request: Request) -> Response:
        relative = request.path.lstrip("/") or "index.html"
        target = (self._folder / relative).resolve()
        if self._folder not in target.parents or not target.is_file():
            return error_response("Not found", 404)
        content_type = mimetypes.guess_type(target.name)[0]
        return Response(
            200, target.read_bytes(), content_type or "application/octet-stream"
        )
