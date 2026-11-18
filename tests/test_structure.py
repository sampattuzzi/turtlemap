import pytest

from code_blueprints.analysis.project import Project
from code_blueprints.analysis.metrics.code_graph import QueryError
from code_blueprints.analysis.structure import Structure
from tests.conftest import ProjectFactory

ACCOUNT = """
class Account:
    def __init__(self) -> None:
        self.balance = 0
        self.history: list[int] = []
        self.name = ""
        self.email = ""

    def deposit(self, amount: int) -> None:
        self.balance += amount
        self.history.append(amount)

    def statement(self) -> list[int]:
        return self.history

    def rename(self, name: str) -> None:
        self.name = name

    def contact(self) -> str:
        return self.email + self.name
"""

GUARDED = """
import threading


class Guarded:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.count = 0
        self.label = ""

    def bump(self) -> None:
        with self.lock:
            self.count += 1

    def total(self) -> int:
        with self.lock:
            return self.count

    def tag(self, text: str) -> None:
        with self.lock:
            self.label = text

    def shout(self) -> str:
        with self.lock:
            return self.label.upper()
"""

SHOP = {
    "shop/basket.py": """
        class Basket:
            def __init__(self) -> None:
                self.items: list[float] = []

            def total(self) -> float:
                return sum(self.items)
    """,
    "shop/pricing.py": """
        from shop.basket import Basket


        def discounted(basket: Basket) -> float:
            return basket.total() * 0.9


        def clear(basket: Basket) -> None:
            basket.items = []
    """,
    "shop/report.py": """
        from shop.pricing import discounted
        from shop.basket import Basket


        def line(basket: Basket) -> str:
            return str(discounted(basket))


        def banner() -> str:
            return "report"
    """,
    "shop/ping.py": """
        def ping() -> str:
            return pong()


        def pong() -> str:
            return "pong"
    """,
    "shop/echo.py": """
        from shop.ping import ping


        def echo() -> str:
            return ping()


        def back() -> str:
            return "back"
    """,
    "tests/test_report.py": """
        from shop.report import line
        from shop.basket import Basket


        def test_line() -> None:
            assert line(Basket())
    """,
}


def test_every_edge_id_resolves_to_a_node(make_project: ProjectFactory) -> None:
    project = make_project(SHOP)

    structure = make_structure(project)

    ids = project.overview()["edges"]["ids"]
    assert ids and all(node_id in structure.nodes for node_id in ids)


def test_class_with_two_field_groups_splits_in_two(
    make_project: ProjectFactory,
) -> None:
    structure = make_structure(make_project({"bank.py": ACCOUNT}))

    answer = structure.cohesion("Account")

    assert answer["groups"] == 2
    assert answer["label"] == "medium"
    assert sorted(answer["members"]) == [
        ["contact", "rename"],
        ["deposit", "statement"],
    ]


def test_a_method_calling_both_groups_joins_them(make_project: ProjectFactory) -> None:
    joined = (
        ACCOUNT
        + "\n    def welcome(self, amount: int) -> None:\n        self.deposit(amount)\n        self.rename('new')\n"
    )
    structure = make_structure(make_project({"bank.py": joined}))

    assert structure.cohesion("Account")["groups"] == 1


def test_a_field_every_method_uses_is_reported_as_a_hub(
    make_project: ProjectFactory,
) -> None:
    structure = make_structure(make_project({"guarded.py": GUARDED}))

    answer = structure.cohesion("Guarded")

    assert answer["groups"] == 1
    assert answer["hubs"] == ["lock"]
    assert answer["groups_without_hubs"] == 2


def test_a_class_with_one_method_is_not_measured(make_project: ProjectFactory) -> None:
    structure = make_structure(make_project(SHOP))

    answer = structure.cohesion("Basket")

    assert answer["groups"] is None
    assert answer["label"] == "n/a"


def test_module_with_an_unrelated_function_has_two_groups(
    make_project: ProjectFactory,
) -> None:
    structure = make_structure(make_project(SHOP))

    linked = structure.cohesion("shop/ping.py")
    unlinked = structure.cohesion("shop/report.py")

    assert linked["groups"] == 1
    assert unlinked["groups"] == 2


def test_a_constant_two_functions_share_links_them(
    make_project: ProjectFactory,
) -> None:
    source = """
        LIMIT = 10


        def clamp(n: int) -> int:
            return min(n, LIMIT)


        def describe() -> str:
            return f"up to {LIMIT}"
    """
    structure = make_structure(make_project({"limits.py": source}))

    assert structure.cohesion("limits.py")["groups"] == 1


def test_one_call_is_loose_coupling(make_project: ProjectFactory) -> None:
    structure = make_structure(make_project(SHOP))

    answer = structure.coupling("shop/echo.py", "shop/ping.py")

    assert answer["label"] == "loose"
    assert answer["a_to_b"]["edges"] == 1
    assert answer["b_to_a"]["edges"] == 0


def test_writing_another_module_s_fields_is_tight_coupling(
    make_project: ProjectFactory,
) -> None:
    structure = make_structure(make_project(SHOP))

    answer = structure.coupling("shop/pricing.py", "shop/basket.py")

    assert answer["label"] == "tight"
    assert "writes" in answer["a_to_b"]["kinds"]


def test_methods_sharing_a_field_one_writes_are_moderately_coupled(
    make_project: ProjectFactory,
) -> None:
    source = (
        ACCOUNT
        + "\n    def balance_text(self) -> str:\n        return str(self.balance)\n"
    )
    structure = make_structure(make_project({"bank.py": source}))

    writer = structure.coupling("Account.deposit", "Account.balance_text")
    readers = structure.coupling("Account.statement", "Account.deposit")

    assert writer["label"] == "moderate"
    assert writer["shared_fields"] == {"f:bank.py:Account.balance": {"written": True}}
    assert readers["label"] == "loose"
    assert readers["shared_fields"] == {"f:bank.py:Account.history": {"written": False}}


def test_unconnected_parts_have_no_coupling(make_project: ProjectFactory) -> None:
    structure = make_structure(make_project(SHOP))

    assert structure.coupling("shop/ping.py", "shop/basket.py")["label"] == "none"


def test_overlapping_parts_cannot_be_compared(make_project: ProjectFactory) -> None:
    structure = make_structure(make_project(SHOP))

    with pytest.raises(QueryError):
        structure.coupling("shop", "shop/ping.py")


def test_instability_leaves_tests_out_of_the_dependants(
    make_project: ProjectFactory,
) -> None:
    structure = make_structure(make_project(SHOP))
    report = structure.nodes["mod:shop/report.py"]

    without_tests = structure.instability(report)
    with_tests = structure.instability(report, include_tests=True)

    assert (without_tests["ca"], without_tests["ce"]) == (0, 2)
    assert without_tests["instability"] == 1.0
    assert with_tests["ca"] == 1


def test_a_function_doing_two_separate_things_has_two_strands(
    make_project: ProjectFactory,
) -> None:
    source = """
        class Pair:
            def __init__(self) -> None:
                self.a = 0
                self.b = 0

            def both(self, x: int, y: int) -> None:
                self.a = x * 2
                self.b = y + 1

            def one(self, x: int) -> int:
                doubled = x * 2
                return doubled + 1
    """
    structure = make_structure(make_project({"pair.py": source}))

    assert structure.cohesion("Pair.both")["groups"] == 2
    assert structure.cohesion("Pair.one")["groups"] == 1


def test_names_resolve_from_paths_dotted_modules_and_qualified_names(
    make_project: ProjectFactory,
) -> None:
    structure = make_structure(make_project(SHOP))

    assert structure.resolve("shop/basket.py").id == "mod:shop/basket.py"
    assert structure.resolve("shop.basket").id == "mod:shop/basket.py"
    assert structure.resolve("Basket.total").id == "m:shop/basket.py:Basket.total"
    assert structure.resolve("shop").id == "pkg:shop"


def test_an_ambiguous_name_lists_the_candidates(make_project: ProjectFactory) -> None:
    structure = make_structure(
        make_project(
            {"a.py": "def run() -> None: ...\n", "b.py": "def run() -> None: ...\n"}
        )
    )

    with pytest.raises(QueryError) as raised:
        structure.resolve("run")

    assert "fn:a.py:run" in str(raised.value) and "fn:b.py:run" in str(raised.value)


def test_describe_lifts_dependencies_to_modules(make_project: ProjectFactory) -> None:
    structure = make_structure(make_project(SHOP))

    answer = structure.describe("shop/report.py")

    assert {d["id"] for d in answer["depends_on"]} == {
        "mod:shop/pricing.py",
        "mod:shop/basket.py",
    }
    assert [d["id"] for d in answer["used_by"]] == ["mod:tests/test_report.py"]


def test_blueprint_lists_nodes_and_their_wires(make_project: ProjectFactory) -> None:
    structure = make_structure(make_project(SHOP))

    answer = structure.blueprint("discounted")

    assert "Return" in answer["text"]
    assert "←" in answer["text"]


def test_reports_a_function_that_is_too_long(make_project: ProjectFactory) -> None:
    body = "".join(f"    total += {n}\n" for n in range(60))
    structure = make_structure(
        make_project(
            {
                "app/long.py": f"def long() -> int:\n    total = 0\n{body}    return total\n"
            }
        )
    )

    oversized = structure.report()["oversized"]

    assert [(item["id"], item["over"]) for item in oversized] == [
        ("fn:app/long.py:long", ["lines"])
    ]


def test_counts_branches_loops_and_conditions_as_complexity(
    make_project: ProjectFactory,
) -> None:
    structure = make_structure(make_project({"app/branchy.py": """
                def branchy(items: list[int], flag: bool) -> int:
                    total = 0
                    for item in items:
                        if item > 0 and flag:
                            total += item
                        elif item < 0 or not flag:
                            total -= 1 if flag else 2
                    while total > 100:
                        total //= 2
                    return total
            """}))

    answer = structure.describe("fn:app/branchy.py:branchy")

    assert answer["size"] == {"lines": 10, "complexity": 8}


def test_reports_a_file_with_too_many_lines(make_project: ProjectFactory) -> None:
    constants = "".join(f"VALUE_{n} = {n}\n" for n in range(520))
    structure = make_structure(make_project({"app/table.py": constants}))

    oversized = structure.report()["oversized"]

    assert [(item["id"], item["size"]["lines"]) for item in oversized] == [
        ("mod:app/table.py", 520)
    ]


def test_leaves_tests_out_of_the_size_report(make_project: ProjectFactory) -> None:
    constants = "".join(f"VALUE_{n} = {n}\n" for n in range(520))
    structure = make_structure(make_project({"tests/test_table.py": constants}))

    assert structure.report()["oversized"] == []


def make_structure(project: Project) -> Structure:
    return Structure(project.overview(), project.function)
