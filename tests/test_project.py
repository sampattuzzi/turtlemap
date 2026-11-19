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


STOCK = """
    from dataclasses import dataclass
    from typing import Optional

    from shop.models import Item


    @dataclass
    class Shelf:
        by_name: dict[str, Item]
        later: Optional[list[Item]]
        labels: list[str]
"""

LONG_TYPE = "dict[tuple[str, str, str], Callable[[Request, dict[str, str]], Awaitable[Response]]]"

ROUTES = f"""
    from dataclasses import dataclass


    @dataclass
    class Table:
        handlers: {LONG_TYPE}
"""


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


def expect_holds(pin: dict[str, Any], class_name: str) -> None:
    assert pin["items"] == {"path": "src/shop/models.py", "sym": class_name}


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


def test_links_list_field_to_the_class_it_holds(make_project: ProjectFactory) -> None:
    assert (
        "f:src/shop/models.py:Basket.items",
        "cls:src/shop/models.py:Item",
        "has",
    ) in edges(make_project(SHOP).overview())


def test_links_dict_field_to_the_class_of_its_values(
    make_project: ProjectFactory,
) -> None:
    project = make_project({**SHOP, "src/shop/stock.py": STOCK})

    assert (
        "f:src/shop/stock.py:Shelf.by_name",
        "cls:src/shop/models.py:Item",
        "has",
    ) in edges(project.overview())


def test_records_the_class_a_container_field_holds(
    make_project: ProjectFactory,
) -> None:
    project = make_project({**SHOP, "src/shop/stock.py": STOCK})

    fields = dict(symbol(project.overview(), "src/shop/stock.py", "Shelf")["fields"])

    expect_holds(fields["by_name"], "Item")
    expect_holds(fields["later"], "Item")
    assert "items" not in fields["labels"]


def test_keeps_the_whole_label_of_a_long_field_type(
    make_project: ProjectFactory,
) -> None:
    project = make_project({**SHOP, "src/shop/routes.py": ROUTES})

    fields = dict(symbol(project.overview(), "src/shop/routes.py", "Table")["fields"])

    assert fields["handlers"]["label"] == LONG_TYPE


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


def test_links_methods_called_on_the_result_of_a_call(
    make_project: ProjectFactory,
) -> None:
    found = edges(
        make_project(
            {
                **SHOP,
                "src/shop/till.py": """
                    from shop.models import Basket


                    def fresh(owner: str) -> Basket:
                        return Basket(owner)


                    def ring_up(owner: str) -> float:
                        return Basket(owner).total()


                    def ring_up_fresh(owner: str) -> str:
                        return fresh(owner).publish()
                """,
            }
        ).overview()
    )

    assert (
        "fn:src/shop/till.py:ring_up",
        "m:src/shop/models.py:Basket.total",
        "calls",
    ) in found
    assert (
        "fn:src/shop/till.py:ring_up_fresh",
        "m:src/shop/models.py:Basket.publish",
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


def test_links_functions_to_fields_they_touch_on_other_objects(
    make_project: ProjectFactory,
) -> None:
    found = edges(
        make_project(
            {
                "box.py": "class Box:\n    def __init__(self) -> None:\n        self.items: list[int] = []\n",
                "use.py": "from box import Box\n\n\ndef empty(box: Box) -> None:\n    box.items = []\n\n\ndef size(box: Box) -> int:\n    return len(box.items)\n",
            }
        ).overview()
    )

    assert ("fn:use.py:empty", "f:box.py:Box.items", "writes") in found
    assert ("fn:use.py:size", "f:box.py:Box.items", "reads") in found


def test_links_code_to_the_constants_it_reads(make_project: ProjectFactory) -> None:
    found = edges(
        make_project(
            {
                "limits.py": "MAX = 3\n",
                "direct.py": "from limits import MAX\n\n\ndef cap(n: int) -> int:\n    return min(n, MAX)\n",
                "dotted.py": "import limits\n\n\ndef cap(n: int) -> int:\n    return min(n, limits.MAX)\n",
                "local.py": "STEP = 2\n\n\ndef bump(n: int) -> int:\n    return n + STEP\n",
            }
        ).overview()
    )

    assert ("fn:direct.py:cap", "c:limits.py:MAX", "reads") in found
    assert ("fn:dotted.py:cap", "c:limits.py:MAX", "reads") in found
    assert ("fn:local.py:bump", "c:local.py:STEP", "reads") in found


def test_links_a_constant_to_the_code_its_value_names(
    make_project: ProjectFactory,
) -> None:
    found = edges(
        make_project(
            {
                "tools.py": "class Tool:\n    def __init__(self, run: object) -> None:\n        self.run = run\n\n\ndef hello() -> str:\n    return 'hi'\n\n\nTOOLS = (Tool(hello),)\n"
            }
        ).overview()
    )

    assert ("c:tools.py:TOOLS", "cls:tools.py:Tool", "creates") in found
    assert ("c:tools.py:TOOLS", "fn:tools.py:hello", "uses") in found


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


def test_lists_fields_assigned_by_unpacking(make_project: ProjectFactory) -> None:
    project = make_project({"src/sim/steps.py": """
        class Step:
            pass


        def compile_steps(size: int) -> tuple[Step, Step]:
            return Step(), Step()


        class Simulator:
            def __init__(self, size: int, label: str) -> None:
                self.step, self.step_with_jacobian = compile_steps(size)
                self.size, self.label = size, label
                self.left, self.right = divmod(size, 2)

            def run(self) -> Step:
                return self.step
    """})
    overview = project.overview()
    simulator = symbol(overview, "src/sim/steps.py", "Simulator")

    assert [(name, pin["label"]) for name, pin in simulator["fields"]] == [
        ("step", "Step"),
        ("step_with_jacobian", "Step"),
        ("size", "int"),
        ("label", "str"),
        ("left", "Any"),
        ("right", "Any"),
    ]
    assert (
        "m:src/sim/steps.py:Simulator.__init__",
        "f:src/sim/steps.py:Simulator.step_with_jacobian",
        "writes",
    ) in edges(overview)
    run = project.function("src/sim/steps.py", "Simulator.run")
    assert run is not None
    outputs = [pin for node in run["graph"]["nodes"] for pin in node["outs"]]
    assert {
        "name": "step",
        "type": {
            "label": "Step",
            "cat": "object",
            "ref": {"path": "src/sim/steps.py", "sym": "Step"},
        },
    } in outputs
