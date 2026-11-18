import subprocess
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from code_blueprints.analysis.diff.project_diff import ProjectDiff
from code_blueprints.analysis.project import Project
from code_blueprints.projects.git import GitError, Repository

BEFORE = {
    "shop/models.py": """
        class Basket:
            def __init__(self, owner: str) -> None:
                self.owner = owner

            def total(self) -> float:
                return 1.0

            def clear(self) -> None:
                pass


        def describe(basket: Basket) -> str:
            return basket.owner


        def unchanged() -> int:
            return 1


        def price(basket: Basket) -> float:
            return round(basket.total(), 2)
    """,
    "shop/legacy.py": """
        def old_helper() -> int:
            return 2
    """,
    "shop/service.py": """
        from shop.models import Basket, describe


        def checkout(owner: str) -> str:
            basket = Basket(owner)
            return describe(basket)
    """,
}

AFTER = {
    "shop/models.py": """
        class Basket:
            def __init__(self, owner: str) -> None:
                self.owner = owner
                self.items: list[str] = []

            def total(self) -> float:
                return 2.0 * len(self.items)


        def describe(basket: Basket) -> str:
            return basket.owner.upper()


        def unchanged() -> int:
            return 1


        def summarise(basket: Basket) -> str:
            return describe(basket)


        def price(basket: Basket) -> float:
            return basket.total()
    """,
    "shop/service.py": """
        from shop.models import Basket, describe


        def checkout(owner: str) -> str:
            basket = Basket(owner)
            return describe(basket)
    """,
    "shop/receipts.py": """
        def print_receipt() -> None:
            print("receipt")
    """,
}


def git(folder: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=folder, check=True, capture_output=True, text=True
    ).stdout


def write(folder: Path, files: dict[str, str]) -> None:
    for relative, source in files.items():
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dedent(source).lstrip())


def make_repository(
    tmp_path: Path,
    before: dict[str, str] = BEFORE,
    after: dict[str, str] = AFTER,
) -> Path:
    folder = tmp_path / "repo"
    folder.mkdir(parents=True)
    git(folder, "init", "-q", "-b", "main")
    git(folder, "config", "user.email", "test@example.com")
    git(folder, "config", "user.name", "Test")
    write(folder, before)
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "before")
    git(folder, "checkout", "-q", "-b", "feature")
    for gone in set(before) - set(after):
        (folder / gone).unlink()
    write(folder, after)
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "after")
    git(folder, "checkout", "-q", "main")
    return folder


def make_diff(
    tmp_path: Path,
    spec: str = "main..feature",
    before: dict[str, str] = BEFORE,
    after: dict[str, str] = AFTER,
) -> ProjectDiff:
    folder = make_repository(tmp_path, before, after)
    repository = Repository(folder)
    diff_range = repository.resolve_range(spec)
    base_files = repository.extract(diff_range.base_sha, tmp_path / "base")
    assert diff_range.head_sha is not None
    head_files = repository.extract(diff_range.head_sha, tmp_path / "head")
    return ProjectDiff(
        Project(tmp_path / "base", base_files),
        Project(tmp_path / "head", head_files),
        repository.changes(diff_range),
        diff_range,
    )


def statuses(diff: ProjectDiff) -> dict[str, str]:
    return dict(diff.summary()["status"])


def review_units(diff: ProjectDiff, path: str) -> dict[str, str]:
    return {unit["id"]: unit["diff"] for unit in diff.summary()["units"][path]}


def fingerprints(diff: ProjectDiff, path: str) -> dict[str, str]:
    return {unit.id: unit.fingerprint for unit in diff.units[path]}


def test_reports_file_level_changes(tmp_path: Path) -> None:
    files = make_diff(tmp_path).summary()["files"]

    assert files == {
        "shop/legacy.py": {"status": "removed"},
        "shop/models.py": {"status": "modified"},
        "shop/receipts.py": {"status": "added"},
    }


def test_marks_added_removed_and_modified_symbols(tmp_path: Path) -> None:
    found = statuses(make_diff(tmp_path))

    assert found["fn:shop/models.py:summarise"] == "added"
    assert found["m:shop/models.py:Basket.clear"] == "removed"
    assert found["m:shop/models.py:Basket.total"] == "modified"
    assert found["fn:shop/models.py:describe"] == "modified"
    assert found["cls:shop/models.py:Basket"] == "modified"
    assert "fn:shop/models.py:unchanged" not in found
    assert found["fn:shop/receipts.py:print_receipt"] == "added"
    assert found["fn:shop/legacy.py:old_helper"] == "removed"


def test_marks_new_fields(tmp_path: Path) -> None:
    assert statuses(make_diff(tmp_path))["f:shop/models.py:Basket.items"] == "added"


def test_ignores_unchanged_files(tmp_path: Path) -> None:
    assert not any("shop/service.py" in key for key in statuses(make_diff(tmp_path)))


def test_keeps_removed_symbols_so_they_can_be_shown(tmp_path: Path) -> None:
    removed = make_diff(tmp_path).summary()["removed"]

    assert [
        method["name"] for method in removed["shop/models.py"]["methods"]["Basket"]
    ] == ["clear"]
    assert [
        symbol["qual"] for symbol in removed["shop/legacy.py"]["module"]["symbols"]
    ] == ["old_helper"]


def test_merges_function_code_with_removed_and_added_lines(tmp_path: Path) -> None:
    payload = make_diff(tmp_path).function("shop/models.py", "Basket.total")

    assert payload is not None
    assert [
        (row[1].strip(), row[2] if len(row) > 2 else None) for row in payload["code"]
    ] == [
        ("def total(self) -> float:", None),
        ("return 1.0", "removed"),
        ("return 2.0 * len(self.items)", "added"),
    ]


def test_serves_removed_functions_from_the_base_revision(tmp_path: Path) -> None:
    payload = make_diff(tmp_path).function("shop/models.py", "Basket.clear")

    assert payload is not None
    assert {node["diff"] for node in payload["graph"]["nodes"]} == {"removed"}
    assert all(row[2] == "removed" for row in payload["code"])


def test_merged_graph_keeps_removed_nodes_and_marks_new_ones(tmp_path: Path) -> None:
    payload = make_diff(tmp_path).function("shop/models.py", "Basket.total")

    assert payload is not None
    by_title: dict[str, Any] = {
        node["title"]: node for node in payload["graph"]["nodes"]
    }
    assert by_title["Calculate"]["diff"] == "added"
    assert by_title["Calculate"]["expr"] == ["2.0 * len(self.items)"]
    assert by_title["Return"]["diff"] == "modified"
    assert "diff" not in by_title["total"]


def test_merged_graph_keeps_removed_calls_and_their_wires(tmp_path: Path) -> None:
    payload = make_diff(tmp_path).function("shop/models.py", "price")

    assert payload is not None
    graph = payload["graph"]
    removed = [node for node in graph["nodes"] if node.get("diff") == "removed"]
    assert [node["title"] for node in removed] == ["round"]
    assert any(
        edge.get("diff") == "removed" and edge["to"] == removed[0]["id"]
        for edge in graph["edges"]
    )
    assert any(edge.get("diff") == "added" for edge in graph["edges"])


def test_unchanged_functions_have_no_diff(tmp_path: Path) -> None:
    payload = make_diff(tmp_path).function("shop/models.py", "unchanged")

    assert payload is not None
    assert all(len(row) == 2 for row in payload["code"])
    assert not any("diff" in node for node in payload["graph"]["nodes"])


def test_merges_outlines_with_removed_items(tmp_path: Path) -> None:
    outline = make_diff(tmp_path).outline("shop/models.py") or []
    basket = next(item for item in outline if item.get("name") == "Basket")

    assert basket["diff"] == "modified"
    assert [
        (item["name"], item.get("diff"))
        for item in basket["body"]
        if item["kind"] == "def"
    ] == [
        ("__init__", "modified"),
        ("total", "modified"),
        ("clear", "removed"),
    ]
    assert (
        next(item for item in outline if item.get("name") == "summarise")["diff"]
        == "added"
    )


def test_three_dot_ranges_compare_against_the_merge_base(tmp_path: Path) -> None:
    folder = make_repository(tmp_path)
    git(folder, "commit", "-q", "--allow-empty", "-m", "main moves on")
    repository = Repository(folder)

    assert (
        repository.resolve_range("main...feature").base_sha
        == git(folder, "rev-parse", "main~1").strip()
    )


def test_compares_against_the_working_copy_when_no_head_is_given(
    tmp_path: Path,
) -> None:
    folder = make_repository(tmp_path)
    (folder / "shop/new_module.py").write_text("def fresh() -> None:\n    pass\n")
    repository = Repository(folder)
    diff_range = repository.resolve_range("main")

    assert diff_range.head_sha is None
    assert [
        (change.status, change.path) for change in repository.changes(diff_range)
    ] == [("added", "shop/new_module.py")]


def test_rejects_unknown_revisions(tmp_path: Path) -> None:
    repository = Repository(make_repository(tmp_path))

    with pytest.raises(GitError, match="Unknown revision"):
        repository.resolve_range("main..nope")


def test_works_from_a_subfolder_of_the_repository(tmp_path: Path) -> None:
    folder = make_repository(tmp_path)
    repository = Repository(folder / "shop")
    diff_range = repository.resolve_range("main..feature")

    assert {change.path for change in repository.changes(diff_range)} == {
        "legacy.py",
        "models.py",
        "receipts.py",
    }
    assert diff_range.head_sha is not None
    assert "receipts.py" in repository.extract(diff_range.head_sha, tmp_path / "sub")


def test_lists_each_changed_function_as_a_review_unit(tmp_path: Path) -> None:
    diff = make_diff(tmp_path)

    assert review_units(diff, "shop/models.py") == {
        "m:shop/models.py:Basket.__init__": "modified",
        "m:shop/models.py:Basket.total": "modified",
        "m:shop/models.py:Basket.clear": "removed",
        "fn:shop/models.py:describe": "modified",
        "fn:shop/models.py:summarise": "added",
        "fn:shop/models.py:price": "modified",
    }
    assert review_units(diff, "shop/legacy.py") == {
        "fn:shop/legacy.py:old_helper": "removed"
    }
    assert review_units(diff, "shop/receipts.py") == {
        "fn:shop/receipts.py:print_receipt": "added"
    }


def test_gives_module_level_changes_their_own_review_unit(tmp_path: Path) -> None:
    before = {"app.py": "import os\n\n\ndef run() -> None:\n    pass\n"}
    after = {"app.py": "import os\nimport sys\n\n\ndef run() -> None:\n    pass\n"}

    assert review_units(make_diff(tmp_path, before=before, after=after), "app.py") == {
        "top:app.py": "modified"
    }


def test_gives_class_body_changes_their_own_review_unit(tmp_path: Path) -> None:
    before = {
        "app.py": "class Box:\n    size = 1\n\n    def open(self) -> None:\n        pass\n"
    }
    after = {
        "app.py": "class Box:\n    size = 2\n\n    def open(self) -> None:\n        pass\n"
    }

    assert review_units(make_diff(tmp_path, before=before, after=after), "app.py") == {
        "body:app.py:Box": "modified"
    }


def test_ignores_blank_lines_left_behind_by_a_removed_function(
    tmp_path: Path,
) -> None:
    before = {"app.py": "X = 1\n\n\ndef gone() -> None:\n    pass\n\n\nY = 2\n"}
    after = {"app.py": "X = 1\n\n\nY = 2\n"}

    assert review_units(make_diff(tmp_path, before=before, after=after), "app.py") == {
        "fn:app.py:gone": "removed"
    }


def test_review_fingerprints_change_only_for_the_function_that_changed(
    tmp_path: Path,
) -> None:
    before = {
        "app.py": "def a() -> int:\n    return 1\n\n\ndef b() -> int:\n    return 1\n"
    }
    first = {
        "app.py": "def a() -> int:\n    return 2\n\n\ndef b() -> int:\n    return 2\n"
    }
    second = {
        "app.py": "def a() -> int:\n    return 2\n\n\ndef b() -> int:\n    return 3\n"
    }

    old = fingerprints(
        make_diff(tmp_path / "one", before=before, after=first), "app.py"
    )
    new = fingerprints(
        make_diff(tmp_path / "two", before=before, after=second), "app.py"
    )

    assert old["fn:app.py:a"] == new["fn:app.py:a"]
    assert old["fn:app.py:b"] != new["fn:app.py:b"]


def test_reports_seen_units_by_their_fingerprints(tmp_path: Path) -> None:
    diff = make_diff(tmp_path)
    seen = set(diff.fingerprints(["fn:shop/models.py:describe", "unknown"]))

    assert diff.seen_units(seen) == ["fn:shop/models.py:describe"]


def test_compares_typescript_with_the_path_aliases_of_each_revision(
    tmp_path: Path,
) -> None:
    config = '{ "compilerOptions": { "paths": { "@lib/*": ["./src/lib/*"] } } }'
    library = """
        export function format(value: number): string {
          return value.toFixed(2);
        }
    """
    before = {
        "web/tsconfig.json": config,
        "web/src/lib/format.ts": library,
        "web/src/view.ts": """
            import { format } from "@lib/format";

            export function show(): string {
              return format(1);
            }
        """,
        "web/src/globals.d.ts": "declare const VERSION: string;\n",
    }
    after = {
        **before,
        "web/src/view.ts": """
            import { format } from "@lib/format";

            export function show(): string {
              return format(2);
            }
        """,
        "web/src/globals.d.ts": "declare const VERSION: number;\n",
    }
    diff = make_diff(tmp_path, before=before, after=after)

    assert diff.summary()["files"] == {"web/src/view.ts": {"status": "modified"}}
    assert statuses(diff)["fn:web/src/view.ts:show"] == "modified"
    head = Project(tmp_path / "head", ["web/src/lib/format.ts", "web/src/view.ts"])
    ids = head.overview()["edges"]["ids"]
    assert "fn:web/src/lib/format.ts:format" in ids
