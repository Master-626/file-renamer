"""Shared test fixtures."""

import pytest
from file_renamer.history import HistoryManager


@pytest.fixture
def temp_dir(tmp_path):
    """Provides a fresh directory with dummy test files."""
    files = [
        "Report 2023.txt",
        "Vacation PHOTO.JPG",
        "data_01#test!.csv",
        "README.md",
    ]
    for f in files:
        (tmp_path / f).write_text("dummy content")
    return tmp_path


@pytest.fixture
def history_mgr(tmp_path):
    """Provides an isolated HistoryManager pointing to a temporary file."""
    history_file = tmp_path / "test_history.json"
    return HistoryManager(history_file=history_file)
