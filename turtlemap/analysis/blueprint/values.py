from dataclasses import dataclass, field, replace

from turtlemap.analysis import model as m
from turtlemap.analysis.types import PinType
from turtlemap.analysis.workspace.parsed import ParsedModule

BOOL = PinType("bool", "bool")


INT = PinType("int", "int")


FLOAT = PinType("float", "float")


STR = PinType("str", "str")


BYTES = PinType("bytes", "bytes")


LIST = PinType("list", "list")


TUPLE = PinType("tuple", "list")


SET = PinType("set", "list")


DICT = PinType("dict", "map")


CALLABLE = PinType("Callable", "callable")


CLASS = PinType("type", "class")


NONE = PinType("None", "none")


@dataclass(frozen=True)
class Value:
    type: PinType = field(compare=False)
    node: str | None = None
    pin: str | None = None
    literal: str | None = None
    annotation: tuple[m.TypeExpr, ParsedModule] | None = field(
        default=None, compare=False
    )


@dataclass(frozen=True)
class Signature:
    parameters: tuple[str, ...]
    result: PinType
    is_async: bool
    anonymous: bool


@dataclass(frozen=True)
class Folded:
    inputs: list[tuple[str, Value]]
    result: PinType
    lines: list[str]


@dataclass(frozen=True, eq=False)
class PendingSelect:
    condition: Value
    when_true: "Binding"
    when_false: "Binding"
    line: int


Binding = Value | PendingSelect


Environment = dict[str, Binding]


def select_type(when_true: Value, when_false: Value) -> PinType:
    if when_true.type.cat == "none" and when_false.type.cat not in ("none", "any"):
        return replace(when_false.type, opt=True)
    if when_false.type.cat == "none" and when_true.type.cat not in ("none", "any"):
        return replace(when_true.type, opt=True)
    return when_true.type if when_true.type.cat != "any" else when_false.type
