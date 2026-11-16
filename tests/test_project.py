from typing import Any, Callable

from code_blueprints.analysis.project import Project

ProjectFactory = Callable[[dict[str, str]], Project]

SHOP = {
    "src/shop/models.py": '''
        """Shop models."""
        import json
        from dataclasses import dataclass
        from enum import Enum

        import requests

        TAX_RATE = 0.2


        class Colour(Enum):
            RED = "red"
            BLUE = "blue"


        @dataclass(frozen=True)
        class Item:
            name: str
            price: float
            colour: Colour


        class ShopError(Exception):
            pass


        class OutOfStock(ShopError):
            pass


        class Basket:
            def __init__(self, owner: str) -> None:
                self.owner = owner
                self.items: list[Item] = []

            def add(self, item: Item) -> None:
                self.items.append(item)

            def total(self) -> float:
                """Sum with tax."""
                return sum(i.price for i in self.items) * (1 + TAX_RATE)

            def publish(self) -> str:
                requests.post("https://example.com", data=json.dumps(self.owner))
                return self.owner
    ''',
    "src/shop/service.py": """
        from shop.models import Basket, Item, Colour


        def checkout(owner: str, name: str) -> float:
            basket = Basket(owner)
            basket.add(Item(name, 2.5, Colour.RED))
            return basket.total()
    """,
}


def symbol(overview: dict[str, Any], path: str, qual: str) -> dict[str, Any]:
    module = next(m for m in overview["modules"] if m["path"] == path)
    return next(s for s in module["symbols"] if s["qual"] == qual)


def edges(overview: dict[str, Any]) -> set[tuple[str, str, str]]:
    ids = overview["edges"]["ids"]
    return {
        (ids[row[0]], ids[row[1]], kind)
        for row in overview["edges"]["rows"]
        for kind in row[2].split(",")
    }


def test_lists_every_python_module(make_project: ProjectFactory) -> None:
    overview = make_project(SHOP).overview()

    assert [m["path"] for m in overview["modules"]] == [
        "src/shop/models.py",
        "src/shop/service.py",
    ]


def test_classifies_dataclass_as_struct_with_typed_fields(
    make_project: ProjectFactory,
) -> None:
    item = symbol(make_project(SHOP).overview(), "src/shop/models.py", "Item")

    assert (item["cat"], item["stereo"]) == ("struct", "dataclass")
    assert [(name, pin["cat"]) for name, pin in item["fields"]] == [
        ("name", "str"),
        ("price", "float"),
        ("colour", "enum"),
    ]


def test_lists_enum_members_with_values(make_project: ProjectFactory) -> None:
    colour = symbol(make_project(SHOP).overview(), "src/shop/models.py", "Colour")

    assert colour["kind"] == "enum"
    assert colour["members"] == [["RED", "'red'"], ["BLUE", "'blue'"]]


def test_marks_subclasses_of_exceptions_as_exceptions(
    make_project: ProjectFactory,
) -> None:
    out_of_stock = symbol(
        make_project(SHOP).overview(), "src/shop/models.py", "OutOfStock"
    )

    assert out_of_stock["stereo"] == "exception"


def test_infers_instance_fields_assigned_in_init(make_project: ProjectFactory) -> None:
    basket = symbol(make_project(SHOP).overview(), "src/shop/models.py", "Basket")

    assert [(name, pin["label"]) for name, pin in basket["fields"]] == [
        ("owner", "str"),
        ("items", "list[Item]"),
    ]


def test_types_method_parameters_from_annotations(make_project: ProjectFactory) -> None:
    basket = symbol(make_project(SHOP).overview(), "src/shop/models.py", "Basket")
    add = next(m for m in basket["methods"] if m["name"] == "add")

    assert [(name, pin["label"]) for name, pin, *_ in add["params"]] == [
        ("self", "Basket"),
        ("item", "Item"),
    ]
    assert add["returns"]["cat"] == "none"


def test_keeps_first_paragraph_of_docstrings(make_project: ProjectFactory) -> None:
    basket = symbol(make_project(SHOP).overview(), "src/shop/models.py", "Basket")

    assert (
        next(m for m in basket["methods"] if m["name"] == "total")["doc"]
        == "Sum with tax."
    )


def test_lists_module_constants_with_types(make_project: ProjectFactory) -> None:
    module = make_project(SHOP).overview()["modules"][0]

    assert module["constants"] == [
        ["TAX_RATE", {"label": "float", "cat": "float"}, "0.2"]
    ]


def test_resolves_imports_through_src_layout(make_project: ProjectFactory) -> None:
    service = make_project(SHOP).overview()["modules"][1]

    assert service["imports"] == [
        {
            "module": "shop.models",
            "path": "src/shop/models.py",
            "names": ["Basket", "Item", "Colour"],
        }
    ]


def test_groups_external_names_by_library(make_project: ProjectFactory) -> None:
    libraries = {lib["id"]: lib for lib in make_project(SHOP).overview()["libraries"]}

    assert list(libraries) == ["lib:stdlib", "lib:requests"]
    assert {"module": "json", "names": ["dumps"]} in libraries["lib:stdlib"]["modules"]
    assert libraries["lib:requests"]["modules"] == [
        {"module": "requests", "names": ["post"]}
    ]


def test_links_subclass_to_its_base(make_project: ProjectFactory) -> None:
    found = edges(make_project(SHOP).overview())

    assert (
        "cls:src/shop/models.py:OutOfStock",
        "cls:src/shop/models.py:ShopError",
        "inherits",
    ) in found
    assert ("cls:src/shop/models.py:Colour", "libn:enum.Enum", "inherits") in found


def test_links_field_to_the_class_of_its_type(make_project: ProjectFactory) -> None:
    assert (
        "f:src/shop/models.py:Item.colour",
        "cls:src/shop/models.py:Colour",
        "has",
    ) in edges(make_project(SHOP).overview())


def test_links_calls_and_constructions_across_modules(
    make_project: ProjectFactory,
) -> None:
    found = edges(make_project(SHOP).overview())

    assert (
        "fn:src/shop/service.py:checkout",
        "cls:src/shop/models.py:Basket",
        "creates",
    ) in found
    assert (
        "fn:src/shop/service.py:checkout",
        "m:src/shop/models.py:Basket.add",
        "calls",
    ) in found
    assert (
        "fn:src/shop/service.py:checkout",
        "m:src/shop/models.py:Basket.total",
        "calls",
    ) in found


def test_links_methods_to_the_fields_they_read_and_write(
    make_project: ProjectFactory,
) -> None:
    found = edges(make_project(SHOP).overview())

    assert (
        "m:src/shop/models.py:Basket.__init__",
        "f:src/shop/models.py:Basket.owner",
        "writes",
    ) in found
    assert (
        "m:src/shop/models.py:Basket.total",
        "f:src/shop/models.py:Basket.items",
        "reads",
    ) in found


def test_links_library_calls_to_library_names(make_project: ProjectFactory) -> None:
    assert (
        "m:src/shop/models.py:Basket.publish",
        "libn:requests.post",
        "calls",
    ) in edges(make_project(SHOP).overview())


def test_reports_files_that_do_not_parse(make_project: ProjectFactory) -> None:
    overview = make_project(
        {"good.py": "x = 1\n", "bad.py": "def broken(:\n"}
    ).overview()

    assert [m["path"] for m in overview["modules"]] == ["good.py"]
    assert [f["path"] for f in overview["failures"]] == ["bad.py"]


def test_picks_up_edits_after_reload(make_project: ProjectFactory) -> None:
    project = make_project({"a.py": "def first() -> None:\n    pass\n"})
    project.overview()
    (project.root / "a.py").write_text("def second() -> None:\n    pass\n")
    project.reload()

    assert [s["name"] for s in project.overview()["modules"][0]["symbols"]] == [
        "second"
    ]
