"""CLI regressions with an isolated history and disposable files."""

import json

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
    assert not (unrelated / "FILE.txt").exists()
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
