from pathlib import Path
from textwrap import dedent
from typing import Callable

import pytest

from code_blueprints.analysis.project import Project

ProjectFactory = Callable[[dict[str, str]], Project]


@pytest.fixture
def make_project(tmp_path: Path) -> ProjectFactory:
    def make(files: dict[str, str]) -> Project:
        for relative, source in files.items():
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(dedent(source).lstrip())
        return Project(tmp_path)

    return make
