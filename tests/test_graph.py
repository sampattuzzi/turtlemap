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


FRAME_KINDS = ("closure", "loop", "branch", "lane", "comprehension")


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
            assert nodes[frame]["kind"] in FRAME_KINDS
            chain.append(frame)
            frame = nodes[frame].get("parent")
        return [*chain, None]

    for node in graph["nodes"]:
        parent = node.get("parent")
        if parent is not None and nodes[parent]["kind"] == "branch":
            assert node["kind"] == "lane", node
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


def test_draws_an_early_return_inside_its_lane(tmp_path: Path) -> None:
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

    lane = the_node(graph, "if")
    entry = nodes_of_kind(graph, "entry")[0]
    early, late = nodes_of_kind(graph, "return")
    assert lane["expr"] == ["current is None"]
    assert lane["parent"] == the_node(graph, "Branch")["id"]
    assert early["parent"] == lane["id"]
    assert source_of(graph, early, "value") == (entry["id"], "fallback")
    assert source_of(graph, late, "value") == (
        the_node(graph, "Break estimate")["id"],
        "value",
    )
    assert exec_order(graph) == [
        "pick -then-> Branch",
        "if -start-> Return",
        "Branch -then-> Return",
    ]
    assert nodes_of_kind(graph, "select") == []


def test_sets_a_variable_in_each_lane_and_reads_it_after_the_branch(
    tmp_path: Path,
) -> None:
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

    variable = the_node(graph, "text")
    stores = nodes_of_kind(graph, "set")
    assert input_pin(variable, "value")["lit"] == "unset"
    assert variable["note"] == "first set by the branch"
    assert [input_pin(store, "value")["lit"] for store in stores] == ['"many"', '"one"']
    assert [store["parent"] for store in stores] == [
        the_node(graph, "if")["id"],
        the_node(graph, "else")["id"],
    ]
    for node in [*stores, the_node(graph, "Get")]:
        assert source_of(graph, node, "text") == (variable["id"], "text")
    assert source_of(graph, the_node(graph, "Return"), "str") == (
        the_node(graph, "Get")["id"],
        "text",
    )
    assert exec_order(graph)[:2] == ["label -then-> text", "text -then-> Branch"]
    assert nodes_of_kind(graph, "select") == []


def test_keeps_a_conditional_expression_as_a_select_without_exec(
    tmp_path: Path,
) -> None:
    graph = make_graph(
        tmp_path,
        """
        def choose(a, c, y, z):
            x = a.b
            return y if c else z
    """,
        "choose",
    )

    assert len(nodes_of_kind(graph, "select")) == 1
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


def test_gives_each_arm_of_an_if_its_own_lane(tmp_path: Path) -> None:
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
    lanes = nodes_of_kind(graph, "lane")
    assert "execOuts" not in branch and branch["outs"] == []
    assert [lane["title"] for lane in lanes] == ["if", "else"]
    assert [lane["reach"] for lane in lanes] == [
        "if user.muted",
        "else · not (user.muted)",
    ]
    assert exec_order(graph) == [
        "notify -then-> Branch",
        "if -start-> log",
        "else -start-> user.send",
        "Branch -then-> Return",
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
        "if -start-> Raise ValueError",
        "Branch -then-> record",
    ]


def test_runs_a_loop_body_inside_the_loop_frame(tmp_path: Path) -> None:
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

    loop = the_node(graph, "For each price in prices")
    variable = the_node(graph, "running")
    added = the_node(graph, "+=")
    assert loop["execOuts"] == ["start"]
    assert [pin["type"]["label"] for pin in loop["outs"]] == ["float"]
    assert added["parent"] == loop["id"]
    assert source_of(graph, added, "running") == (variable["id"], "running")
    assert source_of(graph, added, "value") == (loop["id"], "price")
    assert exec_order(graph) == [
        "total -then-> running",
        "running -then-> For each price in prices",
        "For each price in prices -start-> +=",
        "For each price in prices -then-> Return",
    ]
    assert source_of(graph, the_node(graph, "Return"), "float") == (
        the_node(graph, "Get")["id"],
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


        def sun_position(latitude: float, declination: float, hour_angle: float) -> float:
            north = np.cos(latitude) * np.sin(declination) - np.sin(
                latitude
            ) * np.cos(declination) * np.cos(hour_angle)
            return north
    """,
        "sun_position",
    )

    node = the_node(graph, "north")
    entry = nodes_of_kind(graph, "entry")[0]
    assert len(graph["nodes"]) == 3
    assert node["kind"] == "expr"
    assert node["expr"] == [
        "np.cos(latitude) * np.sin(declination)",
        "- np.sin(latitude)",
        "  * np.cos(declination)",
        "  * np.cos(hour_angle)",
    ]
    assert [pin["name"] for pin in node["ins"]] == [
        "latitude",
        "declination",
        "hour_angle",
    ]
    assert source_of(graph, node, "hour_angle") == (entry["id"], "hour_angle")
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


def test_writes_an_inline_if_condition_into_the_lane(tmp_path: Path) -> None:
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

    lane = the_node(graph, "if")
    assert lane["expr"] == ["count > limit and not done"]
    assert [pin["name"] for pin in lane["ins"]] == ["count", "limit", "done"]
    assert nodes_of_kind(graph, "op") == []
    assert nodes_of_kind(graph, "expr") == []
    assert nodes_of_kind(graph, "select") == []


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
    assert "parent" not in the_node(graph, "For each name in names")


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
    entry = nodes_of_kind(graph, "entry")[0]
    bump = the_node(graph, "+=")
    read = the_node(graph, "Get")
    assert variable["outs"][0]["cell"] is True
    assert variable["outs"][0]["type"]["label"] == "int"
    assert source_of(graph, variable, "value") == (entry["id"], "start")
    assert "parent" not in variable
    assert nodes_of_kind(graph, "set") == [bump]
    assert bump["parent"] == read["parent"] == the_node(graph, "bump")["id"]
    for node in (bump, read):
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


HEATING = """
    from dataclasses import dataclass

    @dataclass
    class Room:
        occupied: bool
        comfort: float
        setback: float
        min_temp: float
        max_temp: float

    def boost_offset(boost: bool) -> float:
        return 1.5 if boost else 0.0

    def clamp(value: float, low: float, high: float) -> float:
        return max(low, min(value, high))

    def heating_plan(rooms: list[Room], outdoor: float, boost: bool) -> list[float]:
        setpoints = []
        for room in rooms:
            if room.occupied and outdoor < 5:
                target = room.comfort + boost_offset(boost)
            else:
                target = room.setback
            setpoints.append(clamp(target, room.min_temp, room.max_temp))
        return setpoints
"""


def test_places_a_variable_first_set_by_a_branch_just_before_it(
    tmp_path: Path,
) -> None:
    graph = make_graph(tmp_path, HEATING, "heating_plan")

    loop = the_node(graph, "For each room in rooms")
    target = next(
        node for node in nodes_of_kind(graph, "var") if node["title"] == "target"
    )
    assert target["parent"] == loop["id"]
    assert input_pin(target, "value")["lit"] == "unset"
    assert "For each room in rooms -start-> target" in exec_order(graph)
    assert "target -then-> Branch" in exec_order(graph)
    assert the_node(graph, "Branch")["parent"] == loop["id"]


def test_appends_to_an_outer_list_through_its_reference(tmp_path: Path) -> None:
    graph = make_graph(tmp_path, HEATING, "heating_plan")

    setpoints = the_node(graph, "setpoints")
    append = the_node(graph, "setpoints.append")
    assert input_pin(setpoints, "value")["lit"] == "[]"
    assert "parent" not in setpoints
    assert source_of(graph, append, "self") == (setpoints["id"], "setpoints")
    assert input_pin(append, "self")["cell"] is True
    assert exec_order(graph)[:2] == [
        "heating_plan -then-> setpoints",
        "setpoints -then-> For each room in rooms",
    ]


def test_reads_fields_inside_the_frame_that_owns_the_value(tmp_path: Path) -> None:
    graph = make_graph(tmp_path, HEATING, "heating_plan")

    breaks = nodes_of_kind(graph, "break")
    assert len(breaks) == 1
    assert breaks[0]["parent"] == the_node(graph, "For each room in rooms")["id"]


def test_ends_a_lane_at_continue_and_break(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def first_big(values: list[int]) -> None:
            for value in values:
                if value < 0:
                    continue
                if value > 100:
                    break
                report(value)

        def report(value):
            pass
    """,
        "first_big",
    )

    for title in ("Continue", "Break"):
        jump = the_node(graph, title)
        assert jump["kind"] == "jump"
        assert jump.get("execIn") is True
        assert "execOut" not in jump and "execOuts" not in jump
    assert exec_order(graph)[-1] == "Branch -then-> report"


def test_stacks_elif_and_else_as_lanes_of_one_branch(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def size(n: int) -> str:
            if n < 10:
                return "small"
            elif n < 100:
                return "medium"
            else:
                return "large"
    """,
        "size",
    )

    branch = the_node(graph, "Branch")
    lanes = nodes_of_kind(graph, "lane")
    assert [lane["title"] for lane in lanes] == ["if", "elif", "else"]
    assert {lane["parent"] for lane in lanes} == {branch["id"]}
    assert lanes[2]["reach"] == "else · not (n < 10) and not (n < 100)"
    assert "execOut" not in branch


def test_draws_match_cases_as_lanes_with_their_captures(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def describe(point) -> str:
            match point:
                case (x, 0):
                    return f"on the x axis at {x}"
                case _:
                    return "elsewhere"
    """,
        "describe",
    )

    branch = the_node(graph, "Match point")
    lanes = nodes_of_kind(graph, "lane")
    assert [pin["name"] for pin in branch["ins"]] == ["subject"]
    assert [lane["title"] for lane in lanes] == ["case [x, 0]", "case _"]
    assert [pin["name"] for pin in lanes[0]["outs"]] == ["x"]
    assert "execOut" not in branch


def test_shows_a_while_condition_on_the_loop_header(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def countdown(start: int) -> int:
            steps = 0
            while start - steps > 0:
                steps += 1
            return steps
    """,
        "countdown",
    )

    loop = the_node(graph, "While")
    assert loop["expr"] == ["start - steps > 0"]
    assert loop["execOuts"] == ["start"]
    assert the_node(graph, "+=")["parent"] == loop["id"]


def test_reaches_a_list_built_up_in_a_loop_by_reference(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def collect(names: list[str], log) -> list[str]:
            found = list(names[:1])
            for name in names:
                log.info(name)
                found.append(name)
            return found
    """,
        "collect",
    )

    [variable] = nodes_of_kind(graph, "var")
    assert variable["title"] == "found"
    assert source_of(graph, the_node(graph, "found.append"), "self") == (
        variable["id"],
        "found",
    )
    assert "cell" not in input_pin(the_node(graph, "log.info"), "self")


def test_draws_a_generator_as_a_pure_frame_that_takes_its_results_back(
    tmp_path: Path,
) -> None:
    graph = make_graph(
        tmp_path,
        """
        from dataclasses import dataclass

        @dataclass
        class Valve:
            zeta: float

        def total(valves: list[Valve]) -> float:
            return sum(valve.zeta for valve in valves)
    """,
        "total",
    )

    frame = the_node(graph, "valve in valves")
    zeta = the_node(graph, "Break Valve")
    results = the_node(graph, "Results")
    entry = nodes_of_kind(graph, "entry")[0]
    assert graph["exec"] == []
    assert frame["kind"] == "comprehension"
    assert frame["badge"] == "Generator"
    assert "execOuts" not in frame and "execIn" not in frame
    assert source_of(graph, frame, "items") == (entry["id"], "valves")
    assert [(pin["name"], pin["type"]["label"]) for pin in frame["outs"]] == [
        ("", "Iterator[float]"),
        ("valve", "Valve"),
    ]
    assert zeta["parent"] == results["parent"] == frame["id"]
    assert source_of(graph, zeta, "valve") == (frame["id"], "valve")
    assert source_of(graph, results, "yield") == (zeta["id"], "zeta")
    assert source_of(graph, the_node(graph, "sum"), "arg1") == (frame["id"], "")


def test_wires_each_filter_into_a_keep_if_pin_of_the_results(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def names(people: list[str], banned: set[str]) -> list[str]:
            return [person for person in people if person not in banned if person]
    """,
        "names",
    )

    frame = the_node(graph, "person in people")
    results = the_node(graph, "Results")
    assert frame["badge"] == "List"
    assert frame["outs"][0]["type"]["label"] == "list[str]"
    assert [pin["name"] for pin in results["ins"]] == ["item", "keep if", "keep if 2"]
    assert [pin["type"]["label"] for pin in results["ins"][1:]] == ["bool", "bool"]
    assert source_of(graph, results, "item") == (frame["id"], "person")
    assert source_of(graph, results, "keep if 2") == (frame["id"], "person")


def test_gives_a_dict_comprehension_a_key_and_a_value_pin(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def lengths(words: list[str]) -> dict[str, int]:
            return {word: len(word) for word in words}
    """,
        "lengths",
    )

    frame = the_node(graph, "word in words")
    results = the_node(graph, "Results")
    assert frame["badge"] == "Dict"
    assert [pin["name"] for pin in results["ins"]] == ["key", "value"]
    assert source_of(graph, results, "key") == (frame["id"], "word")


def test_yields_from_each_further_for_clause_into_the_frame_around_it(
    tmp_path: Path,
) -> None:
    graph = make_graph(
        tmp_path,
        """
        def doubled(grid: list[list[int]], limit: int) -> list[int]:
            return [cell * 2 for row in grid if row for cell in row if cell < limit]
    """,
        "doubled",
    )

    outer = the_node(graph, "row in grid")
    inner = the_node(graph, "cell in row")
    entry = nodes_of_kind(graph, "entry")[0]
    bands = {band["parent"]: band for band in nodes_of_kind(graph, "collect")}
    assert inner["parent"] == outer["id"]
    assert "badge" not in inner
    assert source_of(graph, inner, "items") == (outer["id"], "row")
    assert [(pin["name"], pin["type"]["label"]) for pin in inner["outs"]] == [
        ("", "Iterator[int]"),
        ("cell", "int"),
    ]
    assert outer["outs"][0]["type"]["label"] == "list[int]"
    assert [pin["name"] for pin in bands[inner["id"]]["ins"]] == ["item", "keep if"]
    assert [pin["name"] for pin in bands[outer["id"]]["ins"]] == [
        "yield from",
        "keep if",
    ]
    assert source_of(graph, bands[outer["id"]], "yield from") == (inner["id"], "")
    assert source_of(graph, the_node(graph, "<"), "b") == (entry["id"], "limit")


def test_keeps_a_comprehension_variable_inside_its_frame(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        def shout(name: str, names: list[str]) -> str:
            loud = [name.upper() for name in names]
            return name + str(len(loud))
    """,
        "shout",
    )

    entry = nodes_of_kind(graph, "entry")[0]
    frame = the_node(graph, "name in names")
    assert source_of(graph, the_node(graph, "name.upper"), "self") == (
        frame["id"],
        "name",
    )
    assert source_of(graph, the_node(graph, "Calculate"), "name") == (
        entry["id"],
        "name",
    )


def test_gives_a_field_read_twice_in_a_calculation_one_input(tmp_path: Path) -> None:
    graph = make_graph(
        tmp_path,
        """
        from dataclasses import dataclass

        @dataclass
        class Valve:
            zeta: float | None

        def zetas(valves: list[Valve], fallback: float) -> list[float]:
            return [fallback if x.zeta is None else x.zeta for x in valves]
    """,
        "zetas",
    )

    calculation = the_node(graph, "Calculate")
    assert [pin["name"] for pin in calculation["ins"]] == ["x.zeta", "fallback"]
    assert calculation["expr"] == ["fallback if x.zeta is None else x.zeta"]


def test_keeps_the_key_and_value_pins_in_the_innermost_clause_of_a_dict(
    tmp_path: Path,
) -> None:
    graph = make_graph(
        tmp_path,
        """
        def flatten(groups: list[list[str]]) -> dict[str, int]:
            return {name: len(name) for group in groups for name in group}
    """,
        "flatten",
    )

    outer = the_node(graph, "group in groups")
    inner = the_node(graph, "name in group")
    bands = {band["parent"]: band for band in nodes_of_kind(graph, "collect")}
    assert [pin["name"] for pin in bands[inner["id"]]["ins"]] == ["key", "value"]
    assert [pin["name"] for pin in bands[outer["id"]]["ins"]] == ["yield from"]
    assert outer["outs"][0]["type"]["label"] == "dict[str, int]"
    assert inner["outs"][0]["type"]["label"] == "Iterator"


ROOM_CAPS = """
    from functools import reduce


    def openness(rooms: list[str], emitters: list[tuple[str, float]]) -> tuple:
        caps_by_room: dict[str, list[float]] = {}
        for room_id, cap in emitters:
            caps_by_room.setdefault(room_id, []).append(cap)
        return tuple(
            reduce(min, caps_by_room[room]) if room in caps_by_room else None
            for room in rooms
        )
"""


def test_keeps_a_value_changed_through_a_chained_call_as_a_variable(
    tmp_path: Path,
) -> None:
    graph = make_graph(tmp_path, ROOM_CAPS, "openness")

    caps = the_node(graph, "caps_by_room")
    setdefault = the_node(graph, "caps_by_room.setdefault")
    assert caps["kind"] == "var"
    assert input_pin(caps, "value")["lit"] == "{}"
    assert "lit" not in input_pin(setdefault, "self")
    assert source_of(graph, setdefault, "self") == (caps["id"], "caps_by_room")
    assert exec_order(graph)[:2] == [
        "openness -then-> caps_by_room",
        "caps_by_room -then-> For each room_id, cap in emitters",
    ]


def test_runs_a_calculation_that_reads_a_changing_dict_on_the_execution_line(
    tmp_path: Path,
) -> None:
    graph = make_graph(tmp_path, ROOM_CAPS, "openness")

    expect_well_formed(graph)
    assert "room in rooms -start-> Calculate" in exec_order(graph)
    assert exec_order(graph)[-2:] == [
        "For each room_id, cap in emitters -then-> room in rooms",
        "room in rooms -then-> Return",
    ]


def test_runs_a_call_that_changes_a_value_before_the_call_chained_on_it(
    tmp_path: Path,
) -> None:
    graph = make_graph(tmp_path, ROOM_CAPS, "openness")

    assert exec_order(graph)[2:4] == [
        "For each room_id, cap in emitters -start-> caps_by_room.setdefault",
        "caps_by_room.setdefault -then-> append",
    ]


def test_keeps_a_generator_that_reads_no_changing_value_off_the_execution_line(
    tmp_path: Path,
) -> None:
    graph = make_graph(
        tmp_path,
        """
        def biggest(rooms: dict[str, list[float]]) -> tuple:
            return tuple(max(rooms[room]) for room in rooms)
    """,
        "biggest",
    )

    assert graph["exec"] == []
