from turtlemap.updates.updater import UpdateNotice
from turtlemap.web.framework import Request, Response, Router, json_response


class UpdateService:
    def __init__(self, notice: UpdateNotice) -> None:
        self._notice = notice

    def add_routes(self, router: Router) -> None:
        router.get("/api/update", self.update)

    def update(self, request: Request) -> Response:
        query = request.query
        if "version" not in query:
            return json_response(self._notice.state())
        return json_response(
            self._notice.wait_for_change(
                query["version"], query.get("waiting", ""), _seconds(query.get("wait"))
            )
        )


def _seconds(text: str | None) -> float:
    try:
        return float(text) if text is not None else 0.0
    except ValueError:
        return 0.0
