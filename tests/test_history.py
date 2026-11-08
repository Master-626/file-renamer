"""History anchoring and atomic-save tests."""

import json
import os
from pathlib import Path

import pytest

from file_renamer.history import HistoryManager, RenameRecord


def test_relative_history_file_and_records_are_anchored(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    history = HistoryManager(Path("history.json"))
    history.record_batch([RenameRecord("before.txt", "after.txt")])
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    tx = history.get_latest_active()
    assert tx.records == [
        RenameRecord(str(tmp_path / "before.txt"), str(tmp_path / "after.txt"))
    ]
    history.mark_undone(tx.id)
    assert not (elsewhere / "history.json").exists()
    assert json.loads((tmp_path / "history.json").read_text())[0]["undone"] is True


@pytest.mark.parametrize("error_type", [OSError, KeyboardInterrupt])
def test_failed_atomic_save_preserves_previous_history(
    tmp_path, monkeypatch, error_type
):
    history = HistoryManager(tmp_path / "history.json")
    history.record_batch([RenameRecord(str(tmp_path / "old"), str(tmp_path / "new"))])
    before = history.history_file.read_bytes()

    def fail_replace(src, dst):
        raise error_type("simulated write failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(error_type):
        history.mark_undone(history.get_latest_active().id)
    assert history.history_file.read_bytes() == before
    assert not list(tmp_path.glob(".history-*.tmp"))
