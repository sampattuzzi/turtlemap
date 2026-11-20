import gzip
import json
import os
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from turtlemap.analysis.project import Project
from turtlemap.projects.overview_cache import Overview, OverviewCache

Files = dict[str, str | None]

SHOP: Files = {
    "models.py": """
        class Base:
            size: int = 0
    """,
    "shop.py": """
        from models import Base


        class Box(Base):
            def grow(self) -> int:
                return self.size
    """,
    "notes.py": """
        def remember() -> str:
            return "milk"
    """,
}

ALIASED: Files = {
    "web/tsconfig.json": """
        {"compilerOptions": {"paths": {"@lib/*": ["./src/lib/*"]}}}
    """,
    "web/src/lib/format.ts": """
        export function format(value: number): string {
          return value.toFixed(2);
        }
    """,
    "web/src/other/format.ts": """
        export function format(value: number): string {
          return String(value);
        }
    """,
    "web/src/view.ts": """
        import { format } from "@lib/format";

        export function show(): string {
          return format(1);
        }
    """,
}

EDITS: dict[str, tuple[Files, Files]] = {
    "a body edit": (
        SHOP,
        {"notes.py": 'def remember() -> str:\n    return "eggs"\n'},
    ),
    "a base class that changes kind and gains a field": (
        SHOP,
        {
            "models.py": 'class Base(Exception):\n    size: int = 0\n    name: str = ""\n'
        },
    ),
    "a grandparent class that changes kind": (
        {
            "core.py": "class Root:\n    pass\n",
            "models.py": "from core import Root\n\n\nclass Base(Root):\n    pass\n",
            "shop.py": "from models import Base\n\n\nclass Box(Base):\n    pass\n",
            "store.py": "from models import Base\n\n\nclass Crate(Base):\n    pass\n",
        },
        {"core.py": "class Root(Exception):\n    pass\n"},
    ),
    "a new file that a grandparent class comes from": (
        {
            "models.py": "from core import Root\n\n\nclass Base(Root):\n    pass\n",
            "shop.py": "from models import Base\n\n\nclass Box(Base):\n    pass\n",
        },
        {"core.py": "from enum import Enum\n\n\nclass Root(Enum):\n    pass\n"},
    ),
    "a new file that an import now finds": (
        {
            "shop.py": "from pricing import tax\n\n\ndef total() -> float:\n    return tax(1.0)\n"
        },
        {"pricing.py": "def tax(amount: float) -> float:\n    return amount\n"},
    ),
    "a deleted file that an import used to find": (
        {
            "shop.py": "from pricing import tax\n\n\ndef total() -> float:\n    return tax(1.0)\n",
            "pricing.py": "def tax(amount: float) -> float:\n    return amount\n",
        },
        {"pricing.py": None},
    ),
    "a name added behind a star import": (
        {
            "shop.py": "from helpers import *\n\n\ndef total() -> None:\n    tidy()\n",
            "helpers.py": "def clean() -> None:\n    pass\n",
        },
        {
            "helpers.py": "def clean() -> None:\n    pass\n\n\ndef tidy() -> None:\n    pass\n"
        },
    ),
    "a changed tsconfig path": (
        ALIASED,
        {
            "web/tsconfig.json": '{"compilerOptions": {"paths": {"@lib/*": ["./src/other/*"]}}}\n'
        },
    ),
    "a new tsconfig": (
        {**ALIASED, "web/tsconfig.json": None},
        {"web/tsconfig.json": ALIASED["web/tsconfig.json"]},
    ),
    "a new classic script beside another": (
        {"static/app.js": "function render(value) {\n  return clamp(value);\n}\n"},
        {"static/util.js": "function clamp(value) {\n  return value;\n}\n"},
    ),
}


@pytest.mark.parametrize("edit", EDITS)
def test_matches_a_full_build_after(edit: str, tmp_path: Path) -> None:
    before, changes = EDITS[edit]
    root = make_files(tmp_path / "project", before)
    cache = OverviewCache(tmp_path / "cache")
    first = Project(root)
    cache.overview(first)
    make_files(root, changes)

    result = cache.overview(Project(root), previous=first)

    assert result.changed
    expect_full_build(root, result)


@pytest.mark.parametrize("edit", EDITS)
def test_matches_a_full_build_after_undoing(edit: str, tmp_path: Path) -> None:
    before, changes = EDITS[edit]
    root = make_files(tmp_path / "project", before)
    cache = OverviewCache(tmp_path / "cache")
    first = Project(root)
    cache.overview(first)
    make_files(root, changes)
    edited = Project(root)
    cache.overview(edited, previous=first)
    make_files(root, {path: before.get(path) for path in changes})

    result = cache.overview(Project(root), previous=edited)

    assert result.changed
    expect_full_build(root, result)


def test_rebuilds_only_the_files_an_edit_reaches(tmp_path: Path) -> None:
    root = make_files(tmp_path / "project", SHOP)
    cache = OverviewCache(tmp_path / "cache")
    cache.overview(Project(root))

    make_files(root, {"notes.py": "def remember() -> None:\n    pass\n"})
    after_notes = cache.overview(Project(root))
    make_files(root, {"models.py": "class Base:\n    size: float = 0\n"})
    after_models = cache.overview(Project(root))

    assert after_notes.rebuilt == ("notes.py",)
    assert after_models.rebuilt == ("models.py", "shop.py")
    assert after_models.edited == ("models.py",)


def test_rebuilds_nothing_when_a_file_is_saved_unchanged(tmp_path: Path) -> None:
    root = make_files(tmp_path / "project", SHOP)
    cache = OverviewCache(tmp_path / "cache")
    first = cache.overview(Project(root))
    later = os.stat(root / "models.py").st_mtime + 60
    os.utime(root / "models.py", (later, later))

    again = cache.overview(Project(root))

    assert not again.changed
    assert again.data.compressed() == first.data.compressed()


def test_reopens_from_the_cache_on_disk(tmp_path: Path) -> None:
    root = make_files(tmp_path / "project", SHOP)
    first = Project(root)
    cache = OverviewCache(tmp_path / "cache")
    cache.overview(first)
    cache.save(first)
    make_files(root, {"notes.py": "def remember() -> None:\n    pass\n"})

    reopened = OverviewCache(tmp_path / "cache").overview(Project(root))

    assert reopened.rebuilt == ("notes.py",)
    expect_full_build(root, reopened)


def make_files(root: Path, files: Files) -> Path:
    for relative, source in files.items():
        target = root / relative
        if source is None:
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dedent(source).lstrip())
    return root


def expect_full_build(root: Path, result: Overview) -> None:
    assert without_timing(
        json.loads(gzip.decompress(result.data.compressed()))
    ) == without_timing(Project(root).overview())


def without_timing(overview: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in overview.items() if key != "seconds"}
