from typing import Any, Callable

from turtlemap.analysis.project import Project

ProjectFactory = Callable[[dict[str, str]], Project]

MODEL = {
    "pkg/declarative.py": """
        from typing import Callable


        class Aux:
            def __init__(self, method: Callable[..., float]) -> None:
                self.method = method

            def __get__(self, instance: object, owner: type) -> float:
                return self.method(instance)


        def aux(method: Callable[..., float]) -> Aux:
            return Aux(method)
    """,
    "pkg/model.py": """
        from functools import wraps

        from pkg.declarative import Aux, aux


        def logged(method):
            @wraps(method)
            def wrapper(*args):
                return method(*args)

            return wrapper


        class Heating:
            def __init__(self, rate: float) -> None:
                self.rate = rate

            @aux
            def comfort_cost(self) -> float:
                return self.rate * 2

            @Aux
            def frost_cost(self) -> float:
                return self.rate * 3

            @property
            def total_rate(self) -> float:
                return self.rate

            @logged
            def report(self) -> str:
                return "ok"

            def stage_cost(self) -> float:
                return self.rate * (self.comfort_cost + self.frost_cost) + self.total_rate

            def handlers(self) -> list:
                return [self.report]
    """,
}


def test_reads_methods_made_into_descriptors_as_calls_to_them(
    make_project: ProjectFactory,
) -> None:
    project = make_project(MODEL)

    graph = blueprint(project, "pkg/model.py", "Heating.stage_cost")

    getters = {
        node["title"]: node["target"]["sym"]
        for node in graph["nodes"]
        if node["kind"] == "method"
    }
    assert getters == {
        "self.comfort_cost": "Heating.comfort_cost",
        "self.frost_cost": "Heating.frost_cost",
        "self.total_rate": "Heating.total_rate",
    }
    comfort = next(n for n in graph["nodes"] if n["title"] == "self.comfort_cost")
    assert comfort["outs"][0]["type"]["label"] == "float"


def test_keeps_a_method_passed_as_a_value_a_plain_attribute(
    make_project: ProjectFactory,
) -> None:
    project = make_project(MODEL)

    graph = blueprint(project, "pkg/model.py", "Heating.handlers")

    assert not [node for node in graph["nodes"] if node["kind"] == "method"]


def test_links_a_property_read_to_its_getter_on_the_map(
    make_project: ProjectFactory,
) -> None:
    project = make_project(MODEL)

    found = {
        target
        for source, target, kind in edges(project.overview())
        if source == "m:pkg/model.py:Heating.stage_cost" and kind == "calls"
    }

    assert found == {
        "m:pkg/model.py:Heating.comfort_cost",
        "m:pkg/model.py:Heating.frost_cost",
        "m:pkg/model.py:Heating.total_rate",
    }


def blueprint(project: Project, path: str, qual: str) -> dict[str, Any]:
    found = project.function(path, qual)
    assert found is not None
    graph: dict[str, Any] = found["graph"]
    return graph


def edges(overview: dict[str, Any]) -> set[tuple[str, str, str]]:
    ids = overview["edges"]["ids"]
    return {
        (ids[row[0]], ids[row[1]], kind)
        for row in overview["edges"]["rows"]
        for kind in row[2].split(",")
    }
