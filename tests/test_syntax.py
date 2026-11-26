from turtlemap.analysis.blueprint.syntax import Form, call, chain, infix, method, rows


def test_writes_a_keyword_argument_by_its_name() -> None:
    assert rows(call("round", frozenset({"ndigits"})), ["number", "ndigits"], [""]) == [
        [("text", "round(")],
        [("in", "number")],
        [("text", "ndigits="), ("in", "ndigits")],
        [("text", ")"), ("out", "")],
    ]


def test_names_a_result_that_is_assigned() -> None:
    assert rows(call("load"), [], ["config"]) == [
        [("text", "load(")],
        [("text", ")"), ("text", "→ config"), ("out", "config")],
    ]


def test_keeps_the_colon_of_a_slice_without_a_lower_bound() -> None:
    assert rows(Form("slice"), ["parts", "upper"], [""]) == [
        [("in", "parts")],
        [("text", "[")],
        [("text", ":")],
        [("in", "upper")],
        [("text", "]"), ("out", "")],
    ]


def test_repeats_the_last_operator_between_further_operands() -> None:
    assert rows(infix("and"), ["a", "b", "c"], [""]) == [
        [("in", "a")],
        [("text", "and")],
        [("in", "b")],
        [("text", "and")],
        [("in", "c"), ("out", "")],
    ]


def test_puts_an_awaited_receiver_on_the_first_row() -> None:
    assert rows(method("fetch", "client", awaited=True), ["client"], [""]) == [
        [("text", "await"), ("in", "client")],
        [("text", ".fetch(")],
        [("text", ")"), ("out", "")],
    ]


def test_writes_a_stored_item_between_brackets() -> None:
    assert rows(chain("[", "] ="), ["cache", "key", "value"], []) == [
        [("in", "cache")],
        [("text", "["), ("in", "key")],
        [("text", "] ="), ("in", "value")],
    ]


def test_leads_an_ending_with_its_keyword() -> None:
    assert rows(Form("ending", "return"), ["value"], []) == [
        [("text", "return")],
        [("in", "value")],
    ]


def test_writes_nothing_for_an_unknown_shape() -> None:
    assert rows(Form("unknown"), ["a"], ["b"]) == []
