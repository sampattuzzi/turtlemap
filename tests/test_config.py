from pathlib import Path

import pytest

from turtlemap.config import cache_directory, config_directory


def test_moves_settings_from_the_former_folder_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_former_folder(tmp_path / "config", "comments/project.json")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    folder = config_directory()

    assert folder == tmp_path / "config" / "turtlemap"
    assert (folder / "comments/project.json").read_text() == "kept"
    assert not (tmp_path / "config" / "code-blueprints").exists()


def test_leaves_the_former_folder_when_the_new_one_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_former_folder(tmp_path / "cache", "trees/old")
    (tmp_path / "cache" / "turtlemap").mkdir()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    assert cache_directory() == tmp_path / "cache" / "turtlemap"
    assert (tmp_path / "cache" / "code-blueprints" / "trees/old").exists()


def test_uses_the_new_name_when_nothing_was_saved_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert config_directory() == tmp_path / "turtlemap"


def make_former_folder(base: Path, file: str) -> None:
    target = base / "code-blueprints" / file
    target.parent.mkdir(parents=True)
    target.write_text("kept")
