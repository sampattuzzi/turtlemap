from typing import Any, Callable

from code_blueprints.analysis.project import Project

ProjectFactory = Callable[[dict[str, str]], Project]

SECTIONS = {
    "core/models.py": """
        class ImmutableModel:
            frozen: bool = True
    """,
    "sections/store.py": """
        from typing import Generic, TypeVar

        from core.models import ImmutableModel

        _Section = TypeVar("_Section", bound=ImmutableModel)
        Number = TypeVar("Number", int, float)
        LIMIT = 3


        class SectionStore(Generic[_Section]):
            def load(self, key: str) -> _Section: ...

            def save(self, section: _Section) -> None: ...


        def first_section(sections: list[_Section]) -> _Section:
            return sections[0]


        def doubled(value: Number) -> Number:
            return value * 2
    """,
    "sections/reader.py": """
        from sections.store import _Section


        def latest(sections: list[_Section]) -> _Section:
            return sections[-1]
    """,
}


def test_lists_type_variables_with_their_bounds(make_project: ProjectFactory) -> None:
    summary = module(make_project(SECTIONS).overview(), "sections/store.py")

    bounds = {name: bound for name, _, bound in summary["typeVars"]}

    assert bounds["_Section"]["label"] == "ImmutableModel"
    assert bounds["Number"]["label"] == "int | float"
    assert [name for name, *_ in summary["constants"]] == ["LIMIT"]


def test_marks_a_generic_class_with_its_type_parameters(
    make_project: ProjectFactory,
) -> None:
    summary = module(make_project(SECTIONS).overview(), "sections/store.py")

    store = symbol(summary, "SectionStore")
    first = symbol(summary, "first_section")

    assert [name for name, _ in store["typeParams"]] == ["_Section"]
    assert all("typeParams" not in method for method in store["methods"])
    assert first["typeParams"] == ["_Section"]


def test_links_generic_code_to_its_type_variable_and_on_to_the_bound(
    make_project: ProjectFactory,
) -> None:
    found = edges(make_project(SECTIONS).overview())

    section = "tv:sections/store.py:_Section"
    assert (section, "cls:core/models.py:ImmutableModel", "bound") in found
    assert ("cls:sections/store.py:SectionStore", section, "uses") in found
    assert ("m:sections/store.py:SectionStore.load", section, "uses") in found
    assert ("fn:sections/store.py:first_section", section, "uses") in found
    assert ("fn:sections/reader.py:latest", section, "uses") in found


def module(overview: dict[str, Any], path: str) -> dict[str, Any]:
    found: dict[str, Any] = next(m for m in overview["modules"] if m["path"] == path)
    return found


def symbol(summary: dict[str, Any], qual: str) -> dict[str, Any]:
    found: dict[str, Any] = next(s for s in summary["symbols"] if s["qual"] == qual)
    return found


def edges(overview: dict[str, Any]) -> set[tuple[str, str, str]]:
    ids = overview["edges"]["ids"]
    return {
        (ids[row[0]], ids[row[1]], kind)
        for row in overview["edges"]["rows"]
        for kind in row[2].split(",")
    }
