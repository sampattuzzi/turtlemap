from collections.abc import Sequence
from dataclasses import dataclass

Part = tuple[str, str]
Row = list[Part]

_BRACKETS = {"list": ("[", "]"), "tuple": ("(", ")"), "set": ("{", "}")}


@dataclass(frozen=True)
class Form:
    shape: str
    head: str = ""
    symbols: tuple[str, ...] = ()
    keywords: frozenset[str] = frozenset()
    receiver: str = ""
    closer: str = ""


def call(head: str, keywords: frozenset[str] = frozenset()) -> Form:
    return Form("call", head, keywords=keywords)


def method(
    name: str,
    receiver: str,
    keywords: frozenset[str] = frozenset(),
    *,
    awaited: bool = False,
) -> Form:
    symbols = ("await",) if awaited else ()
    return Form("method", name, symbols, keywords, receiver)


def chain(*symbols: str, head: str = "", closer: str = "") -> Form:
    return Form("chain", head, symbols, closer=closer)


def infix(*symbols: str) -> Form:
    return Form("infix", symbols=symbols)


def rows(form: Form, ins: Sequence[str], outs: Sequence[str]) -> list[Row]:
    shape = _SHAPES.get(form.shape)
    return shape(form, list(ins), list(outs)) if shape else []


def _text(value: str) -> Part:
    return ("text", value)


def _in(name: str) -> Part:
    return ("in", name)


def _out(name: str) -> Part:
    return ("out", name)


def _result(name: str) -> list[Part]:
    return [_text(f"→ {name}"), _out(name)] if name else [_out(name)]


def _closing(closer: str, outs: list[str]) -> list[Row]:
    if not outs:
        return [[_text(closer)]] if closer else []
    first = [_text(closer), *_result(outs[0])] if closer else _result(outs[0])
    return [first, *(_result(name) for name in outs[1:])]


def _argument(form: Form, name: str) -> Row:
    return [_text(f"{name}="), _in(name)] if name in form.keywords else [_in(name)]


def _call(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    return [
        [_text(f"{form.head}(")],
        *(_argument(form, name) for name in ins),
        *_closing(")", outs),
    ]


def _method(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    prefix = [_text(symbol) for symbol in form.symbols]
    receiver = [[*prefix, _in(form.receiver)]] if form.receiver in ins else []
    arguments = [name for name in ins if name != form.receiver]
    return [
        *receiver,
        [_text(f".{form.head}(")],
        *(_argument(form, name) for name in arguments),
        *_closing(")", outs),
    ]


def _infix(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    found: list[Row] = []
    for index, name in enumerate(ins):
        if index:
            symbol = form.symbols[min(index - 1, len(form.symbols) - 1)]
            found.append([_text(symbol)])
        found.append([_in(name)])
    if outs:
        found[-1].extend(_result(outs[0]))
    return found


def _chain(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    found: list[Row] = [[_text(form.head)]] if form.head else []
    for index, name in enumerate(ins):
        symbol = form.symbols[index - 1] if 0 < index <= len(form.symbols) else ""
        found.append([_text(symbol), _in(name)] if symbol else [_in(name)])
    if form.closer or not found:
        return found + _closing(form.closer, outs)
    if outs:
        found[-1].extend(_result(outs[0]))
    return found


def _prefix(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    return [[_text(form.head)], *([_in(name)] for name in ins)] + _closing("", outs)


def _suffix(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    return [*([_in(name)] for name in ins), *_closing(form.head, outs)]


def _index(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    container = [[_in(ins[0])]] if ins else []
    if form.head:
        return container + _closing(form.head, outs)
    keys = [[_in(name)] for name in ins[1:]]
    return [*container, [_text("[")], *keys, *_closing("]", outs)]


def _slice(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    container, *bounds = ins or [""]
    found: list[Row] = [[_in(container)], [_text("[")]] if ins else [[_text("[")]]
    if "lower" in bounds:
        found.append([_in("lower")])
    found.append([_text(":")])
    if "upper" in bounds:
        found.append([_in("upper")])
    if "step" in bounds:
        found.extend([[_text(":")], [_in("step")]])
    return found + _closing("]", outs)


def _fields(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    return [
        *([_in(name)] for name in ins),
        *([_text(f".{name}"), _out(name)] for name in outs),
    ]


def _select(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    words = ["if", "then", "else"]
    found = [[_text(word), _in(name)] for word, name in zip(words, ins)]
    if found and outs:
        found[-1].extend(_result(outs[0]))
    return found


def _build(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    opener, closer = _BRACKETS.get(form.head, ("{", "}"))
    named = form.head not in _BRACKETS
    elements = [
        [_text(f"{name}:"), _in(name)] if named else [_in(name)] for name in ins
    ]
    return [[_text(opener)], *elements, *_closing(closer, outs[:1])]


def _store(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    return [
        *([_in(name)] for name in ins),
        *(_result(name) for name in outs),
    ]


def _ending(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    found: list[Row] = [[_text(form.head)], *([_in(name)] for name in ins)]
    if outs:
        found[-1].extend(_result(outs[0]))
    return found


def _entry(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    return [
        [_text(f"def {form.head}(")],
        *([_text(name), _out(name)] for name in outs),
        [_text(")")],
    ]


def _labelled(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    return [
        *([_text(name), _in(name)] for name in ins),
        *(_result(name) for name in outs),
    ]


def _value(form: Form, ins: list[str], outs: list[str]) -> list[Row]:
    if len(ins) == 1 and len(outs) == 1:
        return [[_in(ins[0]), _out(outs[0])]]
    named = [[_text(name), _out(name)] if name else [_out(name)] for name in outs]
    return [[_in(name)] for name in ins] + named


_SHAPES = {
    "call": _call,
    "method": _method,
    "infix": _infix,
    "chain": _chain,
    "prefix": _prefix,
    "suffix": _suffix,
    "index": _index,
    "slice": _slice,
    "fields": _fields,
    "select": _select,
    "build": _build,
    "store": _store,
    "ending": _ending,
    "entry": _entry,
    "labelled": _labelled,
    "value": _value,
}
