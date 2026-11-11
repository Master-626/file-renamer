"""CLI regressions with an isolated history and disposable files."""

import json
import os

import pytest
from click.testing import CliRunner

import file_renamer.history as history_module
from file_renamer.cli import cli


@pytest.fixture
def isolated_history(tmp_path, monkeypatch):
    history_file = tmp_path / "history.json"
    monkeypatch.setattr(history_module, "HISTORY_FILE", history_file)
    return history_file


def test_cli_undo_after_changing_working_directory(
    tmp_path, monkeypatch, isolated_history
):
    original = tmp_path / "original"
    unrelated = tmp_path / "unrelated"
    original.mkdir()
    unrelated.mkdir()
    (original / "FILE.txt").write_text("original")
    (unrelated / "file.txt").write_text("unrelated")
    runner = CliRunner()
    monkeypatch.chdir(original)
    result = runner.invoke(cli, ["rename", ".", "--pattern", "lower"])
    assert result.exit_code == 0, result.output
    monkeypatch.chdir(unrelated)
    result = runner.invoke(cli, ["undo"])
    assert result.exit_code == 0, result.output
    assert (original / "FILE.txt").read_text() == "original"
    assert (unrelated / "file.txt").read_text() == "unrelated"
    assert {path.name for path in unrelated.iterdir()} == {"file.txt"}
    result = runner.invoke(cli, ["undo"])
    assert result.exit_code != 0
    assert "No active transaction" in result.output


def test_cli_legacy_relative_undo_exits_unsuccessfully(
    tmp_path, monkeypatch, isolated_history
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "renamed.txt").write_text("unrelated")
    before = json.dumps(
        [
            {
                "id": "legacy",
                "timestamp": "then",
                "undone": False,
                "records": [{"src": "original.txt", "dst": "renamed.txt"}],
            }
        ]
    )
    isolated_history.write_text(before)
    result = CliRunner().invoke(cli, ["undo"])
    assert result.exit_code != 0
    assert "legacy history containing relative paths" in result.output
    assert (tmp_path / "renamed.txt").read_text() == "unrelated"
    assert not (tmp_path / "original.txt").exists()
    assert isolated_history.read_text() == before


def test_cli_dry_run_leaves_no_history_or_staging_files(
    tmp_path, monkeypatch, isolated_history
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "FILE.txt").write_text("original")
    result = CliRunner().invoke(cli, ["rename", ".", "--pattern", "lower", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "FILE.txt").read_text() == "original"
    assert not isolated_history.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["FILE.txt"]


def test_recursive_preview_shows_relative_paths(tmp_path, monkeypatch, isolated_history):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "FILE.txt").write_text("nested")
    (tmp_path / "OTHER.txt").write_text("top")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    recursive = runner.invoke(cli, ["rename", ".", "--pattern", "lower", "-r", "--dry-run"])
    assert recursive.exit_code == 0, recursive.output
    assert f"nested{os.sep}FILE.txt" in recursive.output
    assert f"nested{os.sep}file.txt" in recursive.output
    flat = runner.invoke(cli, ["rename", ".", "--pattern", "lower", "--dry-run"])
    assert flat.exit_code == 0, flat.output
    assert f"nested{os.sep}" not in flat.output
    assert "OTHER.txt" in flat.output
    assert (nested / "FILE.txt").read_text() == "nested"
    assert (tmp_path / "OTHER.txt").read_text() == "top"
    assert not isolated_history.exists()


@pytest.mark.parametrize("occupier", ["directory", "dangling-symlink", "other-extension"])
def test_dry_run_rejects_occupied_destination(
    tmp_path, monkeypatch, isolated_history, occupier
):
    monkeypatch.chdir(tmp_path)
    if occupier == "other-extension":
        (tmp_path / "notes.md").write_text("md")
        (tmp_path / "notes.txt").write_text("txt")
        args = ["rename", ".", "--ext", "md", "--replace", ".md", ".txt", "--dry-run"]
    else:
        (tmp_path / "a.txt").write_text("payload")
        occupied = tmp_path / "pre_a.txt"
        if occupier == "directory":
            occupied.mkdir()
        else:
            occupied.symlink_to("missing-target")
        args = ["rename", ".", "--prefix", "pre_", "--dry-run"]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    assert "overwrite" in result.output
    assert "No changes were written" in result.output
    if occupier == "other-extension":
        assert (tmp_path / "notes.md").read_text() == "md"
        assert (tmp_path / "notes.txt").read_text() == "txt"
    else:
        assert (tmp_path / "a.txt").read_text() == "payload"
        if occupier == "dangling-symlink":
            assert (tmp_path / "pre_a.txt").is_symlink()
        else:
            assert (tmp_path / "pre_a.txt").is_dir()
    assert not isolated_history.exists()
    assert list(tmp_path.glob(".file-renamer-*")) == []


def test_dry_run_allows_rename_chain(tmp_path, monkeypatch, isolated_history):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "pre_a.txt").write_text("b")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["rename", ".", "--prefix", "pre_", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry-run mode active" in result.output
    assert (tmp_path / "a.txt").read_text() == "a"
    assert (tmp_path / "pre_a.txt").read_text() == "b"
    assert not isolated_history.exists()


def test_cli_replace_renames_and_undoes(tmp_path, monkeypatch, isolated_history):
    (tmp_path / "IMG_0001.JPEG").write_text("pic")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "rename",
            ".",
            "--replace",
            "IMG_",
            "vacation_",
            "--replace",
            ".JPEG",
            ".jpg",
            "--pattern",
            "lower",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "vacation_0001.jpg").read_text() == "pic"
    assert not (tmp_path / "IMG_0001.JPEG").exists()
    result = runner.invoke(cli, ["undo"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "IMG_0001.JPEG").read_text() == "pic"
    assert not (tmp_path / "vacation_0001.jpg").exists()


def test_cli_replace_rejects_path_separators_and_empty_text(
    tmp_path, monkeypatch, isolated_history
):
    (tmp_path / "A.txt").write_text("payload")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    escaped = runner.invoke(cli, ["rename", ".", "--replace", "A", "A/../B"])
    assert escaped.exit_code != 0
    assert "single filename" in escaped.output
    empty = runner.invoke(cli, ["rename", ".", "--replace", "", "x"])
    assert empty.exit_code != 0
    assert "must not be empty" in empty.output
    assert (tmp_path / "A.txt").read_text() == "payload"
    assert not (tmp_path / "B.txt").exists()
    assert not isolated_history.exists()


def test_cli_compound_extension_and_hidden_suffix(tmp_path, monkeypatch, isolated_history):
    (tmp_path / "archive.tar.gz").write_text("gz")
    (tmp_path / "notes.txt").write_text("txt")
    (tmp_path / ".env.local").write_text("secret")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    listed = runner.invoke(cli, ["list", ".", "--ext", "tar.gz"])
    assert listed.exit_code == 0, listed.output
    assert "archive.tar.gz" in listed.output
    assert "notes.txt" not in listed.output
    hidden = runner.invoke(cli, ["rename", ".", "--suffix", "_bak", "--dry-run"])
    assert hidden.exit_code == 0, hidden.output
    assert ".env_bak.local" in hidden.output
    assert ".env.local_bak" not in hidden.output
    assert (tmp_path / ".env.local").read_text() == "secret"
    renamed = runner.invoke(cli, ["rename", ".", "--ext", ".tar.gz", "--prefix", "bak_"])
    assert renamed.exit_code == 0, renamed.output
    assert (tmp_path / "bak_archive.tar.gz").read_text() == "gz"
    assert (tmp_path / "notes.txt").read_text() == "txt"
    assert (tmp_path / ".env.local").read_text() == "secret"


def test_cli_rejects_parent_directory_prefix(tmp_path, monkeypatch, isolated_history):
    directory = tmp_path / "files"
    directory.mkdir()
    (directory / "A.txt").write_text("payload")
    monkeypatch.chdir(directory)
    result = CliRunner().invoke(cli, ["rename", ".", "--prefix", "../"])
    assert result.exit_code != 0
    assert "single filename" in result.output
    assert (directory / "A.txt").read_text() == "payload"
    assert not (tmp_path / "A.txt").exists()
    assert not isolated_history.exists()
