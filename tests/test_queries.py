from tests.conftest import Running


def test_answers_structure_queries_for_both_roles(running: Running) -> None:
    for agent in (False, True):
        status, answer = running.call(
            "/api/query/cohesion?name=Square.area", agent=agent
        )

        assert status == 200
        assert answer["node"]["id"] == "m:shapes.py:Square.area"
        assert "strand" in answer["text"]


def test_reports_a_missing_name_as_a_bad_request(running: Running) -> None:
    status, answer = running.call("/api/query/describe?name=Circle")

    assert status == 400
    assert "Nothing called 'Circle'" in answer["error"]


def test_rejects_an_unknown_query(running: Running) -> None:
    status, answer = running.call("/api/query/shout")

    assert status == 404
    assert "cohesion" in answer["error"]


def test_rebuilds_after_the_project_is_reloaded(running: Running) -> None:
    running.call("/api/query/find?text=Square")
    (running.project / "shapes.py").write_text(
        "class Circle:\n    def area(self, r: float) -> float:\n        return r * r\n"
    )
    project = running.host.project()
    assert project is not None
    project.reload()

    status, answer = running.call("/api/query/find?text=Circle")

    assert status == 200
    assert answer["matches"][0]["id"] == "cls:shapes.py:Circle"
