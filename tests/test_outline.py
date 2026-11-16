from typing import Callable

from code_blueprints.analysis.project import Project

ProjectFactory = Callable[[dict[str, str]], Project]

SOURCE = '''
    """Module doc
    over two lines."""
    import os
    import sys
    from typing import Any

    LIMIT = 3


    @decorate
    class Thing:
        """A thing."""

        size: int = 0

        def grow(self, by: int) -> None:
            """Grow it."""
            # bigger
            self.size += by

            return None
'''


def test_folds_consecutive_imports_into_one_row(make_project: ProjectFactory) -> None:
    outline = make_project({"m.py": SOURCE}).outline("m.py") or []

    assert outline[1] == {"kind": "imports", "no": 3, "text": "import os", "count": 3}


def test_marks_multi_line_docstrings_as_foldable(make_project: ProjectFactory) -> None:
    outline = make_project({"m.py": SOURCE}).outline("m.py") or []

    assert (outline[0]["kind"], outline[0]["multi"]) == ("doc", True)


def test_nests_class_body_with_decorators_and_methods(
    make_project: ProjectFactory,
) -> None:
    outline = make_project({"m.py": SOURCE}).outline("m.py") or []
    thing = outline[3]

    assert (thing["kind"], thing["name"], thing["decorators"]) == (
        "class",
        "Thing",
        [[10, "@decorate"]],
    )
    assert [(item["kind"], item.get("name")) for item in thing["body"]] == [
        ("doc", None),
        ("stmt", None),
        ("def", "grow"),
    ]


def test_function_code_drops_docstring_comments_and_blank_lines(
    make_project: ProjectFactory,
) -> None:
    payload = make_project({"m.py": SOURCE}).function("m.py", "Thing.grow")

    assert payload is not None
    assert payload["code"] == [
        [16, "    def grow(self, by: int) -> None:"],
        [19, "        self.size += by"],
        [21, "        return None"],
    ]


def test_has_no_outline_for_unknown_files(make_project: ProjectFactory) -> None:
    assert make_project({"m.py": SOURCE}).outline("missing.py") is None
