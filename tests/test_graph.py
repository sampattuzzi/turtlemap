import textwrap
from pathlib import Path
from typing import Any

from turtlemap.analysis.blueprint.canvas import MAX_NODES
from turtlemap.analysis.blueprint.builder import build_function_graph
from turtlemap.analysis.types import TypeSystem
from turtlemap.analysis.workspace.workspace import Workspace

REALISTIC_MODULE = """
    import dataclasses
    import logging
    import time
    from dataclasses import dataclass, field
    from typing import Optional

    from shop.pricing import discount_for, Money

    logger = logging.getLogger(__name__)
    DEFAULT_CURRENCY = "GBP"


    @dataclass(frozen=True)
    class Item:
        sku: str
        price: Money
        quantity: int = 1


    @dataclass
    class Basket:
        owner: str
        items: list[Item] = field(default_factory=list)
        voucher: Optional[str] = None

        def total(self) -> float:
            subtotal = sum(item.price.amount * item.quantity for item in self.items)
            if self.voucher is None:
                return subtotal
            return subtotal - discount_for(self.voucher, subtotal)

        def add(self, item: Item) -> None:
            for existing in self.items:
                if existing.sku == item.sku:
                    raise ValueError(f"{item.sku} is already in the basket")
            self.items.append(item)
            logger.info("added %s", item.sku)

        def describe(self) -> str:
            lines = [f"{item.quantity} x {item.sku}" for item in self.items]
            return "\\n".join(lines) if lines else "empty"


    class Checkout:
        def __init__(self, basket: Basket, clock=time.time) -> None:
            self.basket = basket
            self.clock = clock
            self.attempts = 0

        def pay(self, card: str, *, retries: int = 3) -> bool:
            started = self.clock()
            while self.attempts < retries:
                self.attempts += 1
                try:
                    receipt = self._charge(card, self.basket.total())
                except TimeoutError as error:
                    logger.warning("retrying after %s", error)
                    continue
                else:
                    self._record(receipt, elapsed=self.clock() - started)
                    return True
                finally:
                    logger.debug("attempt %d", self.attempts)
            return False

        def _charge(self, card: str, amount: float) -> str:
            with open("/dev/null", "w") as sink:
                sink.write(f"{card}:{amount}")
            return card[-4:]

        def _record(self, receipt: str, elapsed: float) -> None:
            match receipt:
                case "0000":
                    logger.error("test card")
                case str(code) if code.isdigit():
                    self.basket = dataclasses.replace(self.basket, voucher=None)
                case _:
                    pass

        async def refresh(self, client) -> Optional[Basket]:
            data = await client.fetch(self.basket.owner)
            if not data:
                return None
            items = [Item(sku=row["sku"], price=Money(row["amount"])) for row in data]
            return Basket(owner=self.basket.owner, items=items)

        @classmethod
        def empty(cls, owner: str) -> "Checkout":
            return cls(Basket(owner))

        @staticmethod
        def currency() -> str:
            return DEFAULT_CURRENCY
"""

PRICING_MODULE = """
    from dataclasses import dataclass


    @dataclass(frozen=True)
    class Money:
        amount: float
        currency: str = "GBP"


    def discount_for(voucher: str, subtotal: float) -> float:
        return subtotal * 0.1 if voucher.startswith("TEN") else 0.0
"""


def make_workspace(
    tmp_path: Path, files: dict[str, str]
) -> tuple[Workspace, TypeSystem]:
    for relative, source in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source))
    workspace = Workspace.discover(tmp_path)
    return workspace, TypeSystem(workspace)


def make_graph(
    tmp_path: Path, source: str, function: str, *, others: dict[str, str] | None = None
) -> dict[str, Any]:
    workspace, types = make_workspace(
        tmp_path, {"pkg/main.py": source, **(others or {})}
    )
    module = workspace.module("pkg/main.py")
    assert module is not None
    graph = build_function_graph(types, module, module.functions[function])
    expect_well_formed(graph)
    return graph


def nodes_of_kind(graph: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [node for node in graph["nodes"] if node["kind"] == kind]


def the_node(graph: dict[str, Any], title: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = [
        node for node in graph["nodes"] if node["title"] == title
    ]
    assert (
        len(matches) == 1
    ), f"expected one node titled {title!r}, found {[node['title'] for node in graph['nodes']]}"
    return matches[0]


def input_pin(node: dict[str, Any], name: str) -> dict[str, Any]:
    pins: list[dict[str, Any]] = node["ins"]
    return next(pin for pin in pins if pin["name"] == name)


def source_of(
    graph: dict[str, Any], node: dict[str, Any], pin: str
) -> tuple[str, str] | None:
    edge = next(
        (
            edge
            for edge in graph["edges"]
            if edge["to"] == node["id"] and edge["tp"] == pin
        ),
        None,
    )
    return (edge["from"], edge["fp"]) if edge is not None else None


def exec_order(graph: dict[str, Any]) -> list[str]:
    titles = {node["id"]: node["title"] for node in graph["nodes"]}
    return [
        f"{titles[edge['from']]} -{edge['fp']}-> {titles[edge['to']]}"
        for edge in graph["exec"]
    ]


def expect_well_formed(graph: dict[str, Any]) -> None:
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert len(nodes) == len(graph["nodes"])
    assert len(nodes_of_kind(graph, "entry")) == 1
    for node in graph["nodes"]:
        assert isinstance(node["line"], int)
        input_names = [pin["name"] for pin in node["ins"]]
        output_names = [pin["name"] for pin in node["outs"]]
        assert len(input_names) == len(set(input_names)), node
        assert len(output_names) == len(set(output_names)), node
        if "execOuts" in node:
            assert len(node["execOuts"]) == len(set(node["execOuts"])), node
    for edge in graph["edges"]:
        assert edge["fp"] in [pin["name"] for pin in nodes[edge["from"]]["outs"]], edge
        assert edge["tp"] in [pin["name"] for pin in nodes[edge["to"]]["ins"]], edge
    for edge in graph["exec"]:
        source, target = nodes[edge["from"]], nodes[edge["to"]]
        assert target.get("execIn") is True, edge
        if edge["fp"] == "then":
            assert source.get("execOut") is True, edge
        else:
            assert edge["fp"] in source.get("execOuts", []), edge
    entry = nodes_of_kind(graph, "entry")[0]
    assert entry.get("execOut", False) == any(
        edge["from"] == entry["id"] for edge in graph["exec"]
    )
    expect_frames_hold_their_wires(graph)


def expect_frames_hold_their_wires(graph: dict[str, Any]) -> None:
    nodes = {node["id"]: node for node in graph["nodes"]}

    def frames_around(node_id: str) -> list[str | None]:
        chain: list[str | None] = []
        frame = nodes[node_id].get("parent")
        while frame is not None:
            assert nodes[frame]["kind"] == "closure"
            chain.append(frame)
            frame = nodes[frame].get("parent")
        return [*chain, None]

    for edge in graph["exec"]:
        target_frame = frames_around(edge["to"])[0]
        if edge["fp"] == "start":
            assert target_frame == edge["from"], edge
        else:
            assert frames_around(edge["from"])[0] == target_frame, edge
    for edge in graph["edges"]:
        around_target = frames_around(edge["to"])
        assert (
            frames_around(edge["from"])[0] in around_target
            or edge["from"] in around_target
        ), edge


def test_reads_attributes_through_a_single_break_node(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        class Box:
            width: float
            height: float

        def area(box: Box) -> float:
            return box.width * box.height
    """,
        "area",
    )

    breaks = nodes_of_kind(graph, "break")
    assert len(breaks) == 1
    assert breaks[0]["title"] == "Break Box"
    assert [pin["name"] for pin in breaks[0]["outs"]] == ["width", "height"]
    assert [pin["type"]["label"] for pin in breaks[0]["outs"]] == ["float", "float"]
    assert breaks[0]["target"] == {"path": "pkg/main.py", "sym": "Box"}


def test_collapses_attribute_chains_read_once_into_one_dotted_output(
    tmp_path: Path,
) -> None:
    graph = make_graph(
        tmp_path,
        """
        def deep(request):
            return request.carryover.persisted.rate
    """,
        "deep",
    )

    assert [pin["name"] for pin in the_node(graph, "Break request")["outs"]] == [
        "carryover.persisted.rate"
    ]


def test_splits_attribute_chains_where_a_prefix_is_shared(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def shared(request):
            return request.carryover.a + request.carryover.b
    """,
        "shared",
    )

    assert [pin["name"] for pin in the_node(graph, "Break request")["outs"]] == [
        "carryover"
    ]
    assert [pin["name"] for pin in the_node(graph, "Break carryover")["outs"]] == [
        "a",
        "b",
    ]


def test_wires_variables_from_the_pin_that_produced_them(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def double(value: int) -> int:
            twice = value * 2
            result = twice
            return result
    """,
        "double",
    )

    entry, twice, returned = (
        nodes_of_kind(graph, "entry")[0],
        the_node(graph, "twice"),
        the_node(graph, "Return"),
    )
    assert len(graph["nodes"]) == 3
    assert twice["expr"] == ["value * 2"]
    assert source_of(graph, twice, "value") == (entry["id"], "value")
    assert source_of(graph, returned, "int") == (twice["id"], "")


def test_turns_if_return_into_select(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def pick(estimate, fallback):
            current = estimate.value
            if current is None:
                return fallback
            return current
    """,
        "pick",
    )

    select = the_node(graph, "Select")
    entry = nodes_of_kind(graph, "entry")[0]
    assert select["expr"] == ["current is None"]
    assert source_of(graph, select, "current") == (
        the_node(graph, "Break estimate")["id"],
        "value",
    )
    assert source_of(graph, select, "if true") == (entry["id"], "fallback")
    assert source_of(graph, select, "if false") == (
        the_node(graph, "Break estimate")["id"],
        "value",
    )
    assert source_of(graph, the_node(graph, "Return"), "value") == (select["id"], "")
    assert nodes_of_kind(graph, "branch") == []


def test_merges_assignments_from_both_branches_into_a_select(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def label(count: int) -> str:
            if count > 1:
                text = "many"
            else:
                text = "one"
            return text
    """,
        "label",
    )

    select = the_node(graph, "Select")
    assert input_pin(select, "if true")["lit"] == '"many"'
    assert input_pin(select, "if false")["lit"] == '"one"'
    assert graph["exec"] == []


def test_pure_function_has_no_exec_wires(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def choose(a, c, y, z):
            x = a.b
            if c:
                return y
            return z
    """,
        "choose",
    )

    assert graph["exec"] == []
    assert not any(node.get("execIn") or node.get("execOut") for node in graph["nodes"])


def test_chains_side_effect_calls_on_the_exec_line(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def save(store, record):
            store.open()
            key = store.put(record)
            store.index[key] = record
            return key
    """,
        "save",
    )

    assert exec_order(graph) == [
        "save -then-> store.open",
        "store.open -then-> store.put",
        "store.put -then-> Set store.index[key]",
        "Set store.index[key] -then-> Return",
    ]


def test_keeps_pure_builtins_and_methods_off_the_exec_line(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def shout(words: list[str]) -> str:
            count = len(words)
            joined = " ".join(words)
            print(joined)
            return joined.upper() * count
    """,
        "shout",
    )

    assert not the_node(graph, "len").get("execIn")
    assert not the_node(graph, "join").get("execIn")
    assert exec_order(graph) == ["shout -then-> print", "print -then-> Return"]


def test_branches_when_an_if_has_side_effects(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def notify(user, message):
            if user.muted:
                log(message)
            else:
                user.send(message)
            return None

        def log(message):
            pass
    """,
        "notify",
    )

    branch = the_node(graph, "Branch")
    assert branch["execOuts"] == ["True", "False"]
    assert exec_order(graph) == [
        "notify -then-> Branch",
        "Branch -True-> log",
        "Branch -False-> user.send",
        "log -then-> Return",
        "user.send -then-> Return",
    ]


def test_ends_the_exec_path_at_an_early_raise(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def check(value):
            if value < 0:
                raise ValueError("negative")
            record(value)

        def record(value):
            pass
    """,
        "check",
    )

    raised = the_node(graph, "Raise ValueError")
    assert input_pin(raised, "message")["lit"] == '"negative"'
    assert exec_order(graph) == [
        "check -then-> Branch",
        "Branch -True-> Raise ValueError",
        "Branch -False-> record",
    ]


def test_loops_run_the_body_from_the_loop_body_label(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def total(prices: list[float]) -> float:
            running = 0.0
            for price in prices:
                running += price
            return running
    """,
        "total",
    )

    loop = the_node(graph, "For each price")
    assert loop["execOuts"] == ["Loop body", "Completed"]
    assert [pin["type"]["label"] for pin in loop["outs"]] == ["float"]
    assert exec_order(graph) == [
        "total -then-> For each price",
        "For each price -Loop body-> Set running +=",
        "For each price -Completed-> Return",
    ]
    assert source_of(graph, the_node(graph, "Return"), "float") == (
        the_node(graph, "Set running +=")["id"],
        "running",
    )


def test_try_routes_handlers_from_labelled_exec_outs(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def load(path):
            try:
                data = read(path)
            except FileNotFoundError:
                return None
            except (ValueError, KeyError) as error:
                report(error)
                raise
            return data

        def read(path):
            pass

        def report(error):
            pass
    """,
        "load",
    )

    attempt = the_node(graph, "Try")
    assert attempt["execOuts"] == [
        "Try",
        "except FileNotFoundError",
        "except (ValueError, KeyError)",
    ]
    assert [pin["name"] for pin in attempt["outs"]] == ["error"]
    assert source_of(graph, the_node(graph, "report"), "error") == (
        attempt["id"],
        "error",
    )
    assert "Try -except FileNotFoundError-> Return" in exec_order(graph)


def test_resolves_calls_into_other_modules(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        from pkg import helpers
        from pkg.helpers import Point, scale

        def run(x: float) -> float:
            point = Point(x, y=2.0)
            return helpers.length(scale(point, factor=x))
    """,
        "run",
        others={"pkg/helpers.py": """
        from dataclasses import dataclass

        @dataclass
        class Point:
            x: float
            y: float

        def scale(point: Point, factor: float) -> Point:
            return point

        def length(point: Point) -> float:
            return point.x
    """},
    )

    make = the_node(graph, "Make Point")
    assert make["target"] == {"path": "pkg/helpers.py", "sym": "Point"}
    assert [pin["name"] for pin in make["ins"]] == ["x", "y"]
    assert [pin["name"] for pin in make["outs"]] == ["Point"]
    scale_node = the_node(graph, "scale")
    assert scale_node["kind"] == "call"
    assert scale_node["target"] == {"path": "pkg/helpers.py", "sym": "scale"}
    assert [pin["name"] for pin in scale_node["ins"]] == ["point", "factor"]
    assert scale_node["outs"][0]["type"]["label"] == "Point"
    length = the_node(graph, "helpers.length")
    assert length["target"] == {"path": "pkg/helpers.py", "sym": "length"}
    assert length["outs"][0]["type"]["label"] == "float"


def test_resolves_calls_through_imports_made_inside_the_function(
    tmp_path: Path,
) -> None:
    graph = make_graph(
        tmp_path,
        """
        def run(x: float) -> float:
            from pkg.helpers import double
            import pkg.helpers as helpers

            return helpers.halve(double(x))
    """,
        "run",
        others={"pkg/helpers.py": """
        def double(x: float) -> float:
            return x * 2

        def halve(x: float) -> float:
            return x / 2
    """},
    )

    assert the_node(graph, "double")["target"] == {
        "path": "pkg/helpers.py",
        "sym": "double",
    }
    assert the_node(graph, "helpers.halve")["target"] == {
        "path": "pkg/helpers.py",
        "sym": "halve",
    }
    assert nodes_of_kind(graph, "var") == []


def test_targets_methods_through_the_receiver_type(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        class Engine:
            def start(self, power: int) -> bool:
                return True

        class Car:
            engine: Engine

            def drive(self) -> bool:
                return self.engine.start(5)
    """,
        "Car.drive",
    )

    start = the_node(graph, "engine.start")
    assert start["kind"] == "method"
    assert start["target"] == {"path": "pkg/main.py", "sym": "Engine.start"}
    assert source_of(graph, start, "self") == (
        the_node(graph, "Break Car")["id"],
        "engine",
    )
    assert input_pin(start, "power")["lit"] == "5"
    entry = nodes_of_kind(graph, "entry")[0]
    assert entry["title"] == "drive"
    assert entry["outs"][0]["type"]["ref"] == {"path": "pkg/main.py", "sym": "Car"}


def test_marks_library_calls_as_external(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        import time
        from dataclasses import replace

        def stamp(record):
            now = time.time()
            return replace(record, at=now)
    """,
        "stamp",
    )

    assert the_node(graph, "time.time")["external"] == "time.time"
    pure_replace = the_node(graph, "replace")
    assert pure_replace["external"] == "dataclasses.replace"
    assert not pure_replace.get("execIn")
    assert exec_order(graph) == ["stamp -then-> time.time", "time.time -then-> Return"]


def test_puts_literals_inline_on_input_pins(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def configure(client):
            client.connect(host="localhost", port=8080, retries=(1, 2), verbose=None)
    """,
        "configure",
    )

    connect = the_node(graph, "client.connect")
    assert {pin["name"]: pin.get("lit") for pin in connect["ins"]} == {
        "self": None,
        "host": '"localhost"',
        "port": "8080",
        "retries": "(1, 2)",
        "verbose": "None",
    }
    assert nodes_of_kind(graph, "lit") == []


def test_formats_f_strings_into_a_format_text_node(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def greet(name: str, count: int) -> str:
            return f"hello {name}, you have {count} messages"
    """,
        "greet",
    )

    text = the_node(graph, "Format text")
    assert [pin["name"] for pin in text["ins"]] == ["name", "count"]
    assert "hello {name}" in text["code"]


def test_notes_awaited_calls(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        async def fetch(client, key):
            value = await client.get_remote(key)
            return value
    """,
        "fetch",
    )

    assert the_node(graph, "client.get_remote")["note"] == "awaits"


def test_pin_names_are_unique_per_node(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def clash(a, b, f):
            values = (a, a, a.x, b.x)
            f(a, a, *b, *b, key=a, **b, **b)
            return {**a, **a}
    """,
        "clash",
    )

    assert [pin["name"] for pin in the_node(graph, "Make tuple")["ins"]] == [
        "a",
        "a 2",
        "x",
        "x 2",
    ]
    assert [pin["name"] for pin in the_node(graph, "f")["ins"]] == [
        "f",
        "a",
        "a 2",
        "*b",
        "*b 2",
        "key",
        "**b",
        "**b 2",
    ]


def test_never_raises_on_odd_syntax(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def odd(x, *args, **kwargs):
            global COUNTER
            COUNTER += 1
            del x[0], kwargs
            assert x, "x must be set"
            y = lambda q: q + x
            z = [i for i in range(10) if i % 2]
            w = {k: v for k, v in kwargs.items()}
            (a, *b), c = x
            x[1:3] = (yield a)
            yield from b
            async def inner():
                pass
            while (n := len(args)) > 0:
                args = args[1:]
                if n == 2:
                    break
                continue
            with open(x) as f, open(y) as (g, h):
                pass
            match x:
                case {"k": v, **rest}:
                    pass
                case [first, *others] if first:
                    pass
            try:
                pass
            except* ValueError:
                pass
            return x if y else ~z, -1, not w, 3 ** 2, c[::2], ...
    """,
        "odd",
    )

    assert len(nodes_of_kind(graph, "return")) >= 1


def test_stops_at_the_node_limit(tmp_path: Path) -> None:
    calls = "\n".join(f"    step_{index}(value)" for index in range(MAX_NODES + 20))
    graph = make_graph(tmp_path, f"def busy(value):\n{calls}\n", "busy")

    assert graph["truncated"] is True
    assert len(graph["nodes"]) == MAX_NODES + 1
    assert graph["nodes"][-1]["kind"] == "return"


def test_builds_well_formed_graphs_for_every_function_of_a_realistic_module(
    tmp_path: Path,
) -> None:
    workspace, types = make_workspace(
        tmp_path,
        {"shop/basket.py": REALISTIC_MODULE, "shop/pricing.py": PRICING_MODULE},
    )

    for path in workspace.index.files:
        module = workspace.module(path)
        assert module is not None
        for function in module.functions.values():
            graph = build_function_graph(types, module, function)
            expect_well_formed(graph)
            assert not any(
                "Not drawn" in node.get("note", "") for node in graph["nodes"]
            ), function.qualname


def test_writes_a_named_calculation_as_one_node(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        import numpy as np


        def arm_reach(rotation: float, inclination: float, turn_angle: float) -> float:
            ahead = np.cos(rotation) * np.sin(inclination) - np.sin(
                rotation
            ) * np.cos(inclination) * np.cos(turn_angle)
            return ahead
    """,
        "arm_reach",
    )

    node = the_node(graph, "ahead")
    entry = nodes_of_kind(graph, "entry")[0]
    assert len(graph["nodes"]) == 3
    assert node["kind"] == "expr"
    assert node["expr"] == [
        "np.cos(rotation) * np.sin(inclination)",
        "- np.sin(rotation)",
        "  * np.cos(inclination)",
        "  * np.cos(turn_angle)",
    ]
    assert [pin["name"] for pin in node["ins"]] == [
        "rotation",
        "inclination",
        "turn_angle",
    ]
    assert source_of(graph, node, "turn_angle") == (entry["id"], "turn_angle")
    assert node["outs"][0]["type"]["cat"] == "float"


def test_keeps_project_calls_as_their_own_nodes_inside_a_calculation(
    tmp_path: Path,
) -> None:
    graph = make_graph(
        tmp_path,
        """
        def price(item):
            return item.cost


        def order_total(item, count: int):
            total = price(item) * count + 1
            return total
    """,
        "order_total",
    )

    calculation = the_node(graph, "total")
    assert calculation["expr"] == ["price(item) * count + 1"]
    assert source_of(graph, calculation, "price(item)") == (
        the_node(graph, "price")["id"],
        "",
    )


def test_folds_unnamed_multi_step_expressions_into_a_check(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def report(items, notify):
            notify(len(items) > 3 and not items[0])
    """,
        "report",
    )

    check = the_node(graph, "Check")
    assert check["expr"] == ["len(items) > 3 and not items[0]"]
    assert [pin["name"] for pin in check["ins"]] == ["items"]
    assert nodes_of_kind(graph, "op") == []


def test_writes_an_inline_if_condition_into_the_branch(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def guard(count: int, limit: int, done: bool, log):
            if count > limit and not done:
                log.write("over")
                level = 1
            else:
                level = 2
            return level
    """,
        "guard",
    )

    branch = the_node(graph, "Branch")
    assert branch["expr"] == ["count > limit and not done"]
    assert [pin["name"] for pin in branch["ins"]] == ["count", "limit", "done"]
    assert nodes_of_kind(graph, "op") == []
    assert nodes_of_kind(graph, "expr") == []
    assert source_of(graph, the_node(graph, "Select"), "condition") == (
        branch["id"],
        "condition",
    )


def test_writes_a_while_condition_into_the_loop(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def drain(queue, limit: int):
            while len(queue) < limit:
                queue.pop()
    """,
        "drain",
    )

    loop = the_node(graph, "While")
    assert loop["expr"] == ["len(queue) < limit"]
    assert [pin["name"] for pin in loop["ins"]] == ["queue", "limit"]


def test_wraps_long_expressions_with_brackets_where_needed(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def rank(alpha: float, beta: float, gamma_adjustment: float, delta: float):
            score = (alpha + beta * gamma_adjustment) * (delta - alpha) ** 2
            return score
    """,
        "rank",
    )

    assert the_node(graph, "score")["expr"] == [
        "(alpha + beta * gamma_adjustment)",
        "* (delta - alpha) ** 2",
    ]


def test_keeps_field_reads_on_project_objects_as_their_own_nodes(
    tmp_path: Path,
) -> None:
    graph = make_graph(
        tmp_path,
        """
        from dataclasses import dataclass


        @dataclass
        class Order:
            cost: float
            count: int


        def order_total(order: Order, tax: float) -> float:
            total = order.cost * order.count + tax
            return total
    """,
        "order_total",
    )

    calculation = the_node(graph, "total")
    breaks = nodes_of_kind(graph, "break")
    assert calculation["expr"] == ["order.cost * order.count + tax"]
    assert [pin["name"] for pin in calculation["ins"]] == [
        "order.cost",
        "order.count",
        "tax",
    ]
    assert len(breaks) == 1
    assert calculation["outs"][0]["type"]["cat"] == "float"


def test_names_long_operands_by_their_pin_in_the_expression(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def combine_measurements(first, second):
            return first


        def build(first_value, second_value, offset: float, flag: bool):
            result = combine_measurements(first_value, second_value) + offset if flag else 0.0
            return result
    """,
        "build",
    )

    result = the_node(graph, "result")
    assert result["expr"] == [
        "combine_measurements(first_… + offset",
        "if flag",
        "else 0.0",
    ]
    assert [pin["name"] for pin in result["ins"]] == [
        "flag",
        "combine_measurements(first_…",
        "offset",
    ]


def test_wires_a_class_chosen_at_runtime_into_the_make_node(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        class Model:
            def __init__(self, size: int) -> None:
                self.size = size

        class MassModel(Model):
            pass

        def build(heavy: bool, size: int) -> Model:
            kind = MassModel if heavy else Model
            return kind(size)
    """,
        "build",
    )

    make = the_node(graph, "Make kind")
    select = the_node(graph, "Select")
    assert source_of(graph, make, "class") == (select["id"], "")
    assert [pin["name"] for pin in make["ins"]] == ["class", "size"]


def test_makes_the_class_itself_when_a_classmethod_calls_cls(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        class Model:
            def __init__(self, size: int) -> None:
                self.size = size

            @classmethod
            def small(cls) -> "Model":
                return cls(1)
    """,
        "Model.small",
    )

    make = the_node(graph, "Make Model")
    assert [pin["name"] for pin in make["ins"]] == ["size"]


def test_draws_a_nested_function_as_a_frame_around_its_body(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def greet_all(names: list[str], greeting: str) -> None:
            def greet(name: str) -> None:
                print(greeting, name)

            for name in names:
                greet(name)
    """,
        "greet_all",
    )
    frame = nodes_of_kind(graph, "closure")[0]
    printed = the_node(graph, "print")
    entry = nodes_of_kind(graph, "entry")[0]
    assert frame["title"] == "greet"
    assert printed["parent"] == frame["id"]
    assert source_of(graph, printed, "greeting") == (entry["id"], "greeting")
    assert source_of(graph, printed, "name") == (frame["id"], "name")
    assert [pin["name"] for pin in frame["outs"]] == ["function", "name"]
    assert frame["outs"][0]["type"]["label"] == "(name) ⇒ None"
    assert {"from": frame["id"], "fp": "start", "to": printed["id"]} in graph["exec"]
    assert "parent" not in the_node(graph, "For each name")


def test_calls_a_nested_function_through_its_function_pin(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def twice(value: int) -> int:
            def double(number: int) -> int:
                return number * 2

            return double(value)
    """,
        "twice",
    )
    frame = next(node for node in nodes_of_kind(graph, "closure"))
    call = next(node for node in nodes_of_kind(graph, "call"))
    assert call["title"] == "double"
    assert source_of(graph, call, "function") == (frame["id"], "function")
    assert [pin["name"] for pin in call["ins"]] == ["function", "number"]


def test_keeps_a_pure_lambda_off_the_execution_line(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def sort_people(people: list[str]) -> list[str]:
            return sorted(people, key=lambda person: person.lower())
    """,
        "sort_people",
    )
    frame = the_node(graph, "Lambda")
    lowered = the_node(graph, "person.lower")
    assert graph["exec"] == []
    assert "execOuts" not in frame
    assert lowered["parent"] == frame["id"]
    assert source_of(graph, lowered, "self") == (frame["id"], "person")
    assert source_of(graph, the_node(graph, "sorted"), "key") == (
        frame["id"],
        "function",
    )


def test_shares_a_captured_local_that_changes_through_one_variable(
    tmp_path: Path,
) -> None:
    graph = make_graph(
        tmp_path,
        """
        def make_counter(start: int):
            count = start

            def bump() -> int:
                nonlocal count
                count += 1
                return count

            return bump
    """,
        "make_counter",
    )
    variable = the_node(graph, "count")
    store = the_node(graph, "Set")
    bump = the_node(graph, "+=")
    read = the_node(graph, "Get")
    assert variable["outs"][0]["cell"] is True
    assert variable["outs"][0]["type"]["label"] == "int"
    assert "parent" not in variable
    assert bump["parent"] == read["parent"] == the_node(graph, "bump")["id"]
    for node in (store, bump, read):
        assert source_of(graph, node, "count") == (variable["id"], "count")
        assert input_pin(node, "count")["cell"] is True


def test_reads_a_module_variable_that_changes_through_a_get_each_time(
    tmp_path: Path,
) -> None:
    graph = make_graph(
        tmp_path,
        """
        CALLS = 0

        def count_call() -> int:
            global CALLS
            before = CALLS
            CALLS += 1
            return before + CALLS
    """,
        "count_call",
    )
    variable = the_node(graph, "CALLS")
    reads = nodes_of_kind(graph, "get")
    assert variable["outs"][0]["cell"] is True
    assert len(reads) == 2
    assert all(
        source_of(graph, read, "CALLS") == (variable["id"], "CALLS") for read in reads
    )
    assert source_of(graph, the_node(graph, "+="), "CALLS") == (variable["id"], "CALLS")


def test_leaves_module_constants_as_plain_values(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        LIMIT = 10

        def capped(value: int) -> int:
            return min(value, LIMIT)
    """,
        "capped",
    )
    limit = the_node(graph, "LIMIT")
    assert "cell" not in limit["outs"][0]
    assert nodes_of_kind(graph, "get") == []


def test_notes_an_async_call_that_is_not_awaited(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        import asyncio

        async def fetch() -> int:
            return 1

        async def start() -> None:
            asyncio.create_task(fetch())
            await fetch()
    """,
        "start",
    )
    started, awaited = nodes_of_kind(graph, "call")
    assert started["note"] == "not awaited"
    assert started["outs"][0]["type"]["label"] == "Coroutine"
    assert awaited["note"] == "awaits"
