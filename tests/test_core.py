"""Filesystem safety regressions; every file lives in pytest's temp directory."""

import json
from pathlib import Path

import pytest

from file_renamer.core import (
    RenamePlan,
    build_rename_plan,
    execute_rename,
    execute_undo,
    find_files,
    preflight_rename,
)
from file_renamer.history import HistoryManager, RenameRecord
from file_renamer.identity import capture_fingerprint


def make_batch(tmp_path):
    directory = tmp_path / "files"
    directory.mkdir()
    originals = {"A.txt": "first payload", "B.txt": "second payload"}
    for name, payload in originals.items():
        (directory / name).write_text(payload)
    return directory, originals


def assert_files(directory, expected):
    assert {p.name: p.read_text() for p in directory.iterdir()} == expected


def test_undo_from_another_directory_never_touches_unrelated_files(
    tmp_path, monkeypatch
):
    original = tmp_path / "original"
    elsewhere = tmp_path / "elsewhere"
    original.mkdir()
    elsewhere.mkdir()
    (original / "FILE.txt").write_text("original content")
    (elsewhere / "file.txt").write_text("unrelated content")
    history = HistoryManager(tmp_path / "history.json")
    monkeypatch.chdir(original)
    count, tx_id = execute_rename(
        build_rename_plan(find_files(Path(".")), pattern="lower"), history
    )
    assert count == 1
    transaction = history.get_latest_active()
    assert transaction.id == tx_id
    assert transaction.records == [
        RenameRecord(
            str(original / "FILE.txt"),
            str(original / "file.txt"),
            capture_fingerprint(original / "file.txt"),
        )
    ]
    monkeypatch.chdir(elsewhere)
    execute_undo(history)
    assert_files(original, {"FILE.txt": "original content"})
    assert_files(elsewhere, {"file.txt": "unrelated content"})
    assert history.get_latest_active() is None


@pytest.mark.parametrize("relative_field", ["src", "dst", "both"])
def test_legacy_relative_history_is_rejected_without_any_changes(
    tmp_path, monkeypatch, relative_field
):
    directory, originals = make_batch(tmp_path)
    monkeypatch.chdir(directory)
    history = HistoryManager(tmp_path / "history.json")
    # Write a legacy fixture directly: new records must always be absolute.
    records = [
        {"src": str(directory / "restored.txt"), "dst": str(directory / "B.txt")},
        {
            "src": "old.txt"
            if relative_field in ("src", "both")
            else str(directory / "old.txt"),
            "dst": "A.txt"
            if relative_field in ("dst", "both")
            else str(directory / "A.txt"),
        },
    ]
    before = json.dumps([{"id": "legacy", "timestamp": "then", "records": records}])
    history.history_file.write_text(before)
    with pytest.raises(ValueError, match="legacy history containing relative paths"):
        execute_undo(history)
    assert_files(directory, originals)
    assert history.history_file.read_text() == before


def test_legacy_absolute_history_without_identity_is_refused(tmp_path):
    directory, _ = make_batch(tmp_path)
    history = HistoryManager(tmp_path / "history.json")
    history.history_file.write_text(
        json.dumps(
            [
                {
                    "id": "legacy",
                    "timestamp": "then",
                    "records": [
                        {
                            "src": str(directory / "original.txt"),
                            "dst": str(directory / "A.txt"),
                        }
                    ],
                }
            ]
        )
    )
    before = history.history_file.read_bytes()
    with pytest.raises(ValueError, match="without file fingerprints"):
        execute_undo(history)
    assert_files(directory, {"A.txt": "first payload", "B.txt": "second payload"})
    assert history.history_file.read_bytes() == before
    assert history.list_all()[0].records[0].fingerprint is None


@pytest.mark.parametrize("problem", ["missing", "occupied", "broken_symlink"])
def test_undo_preflights_entire_batch(tmp_path, problem):
    directory, originals = make_batch(tmp_path)
    history = HistoryManager(tmp_path / "history.json")
    execute_rename(build_rename_plan(find_files(directory), prefix="renamed_"), history)
    if problem == "missing":
        (directory / "renamed_A.txt").unlink()
        expected_error = FileNotFoundError
    elif problem == "occupied":
        (directory / "A.txt").write_text("unrelated")
        expected_error = FileExistsError
    else:
        (directory / "A.txt").symlink_to("does-not-exist")
        expected_error = FileExistsError
    before_history = history.history_file.read_bytes()
    before_names = sorted(p.name for p in directory.iterdir())
    with pytest.raises(expected_error):
        execute_undo(history)
    assert sorted(p.name for p in directory.iterdir()) == before_names
    assert (directory / "renamed_B.txt").read_text() == originals["B.txt"]
    assert history.history_file.read_bytes() == before_history
    if problem == "occupied":
        assert (directory / "A.txt").read_text() == "unrelated"
    if problem == "broken_symlink":
        assert (directory / "A.txt").is_symlink()


@pytest.mark.parametrize("operation", ["rename", "undo"])
@pytest.mark.parametrize("failure_step", [1, 2, 3, 4])
@pytest.mark.parametrize("after_move", [False, True])
@pytest.mark.parametrize("error_type", [OSError, KeyboardInterrupt])
def test_interrupted_batches_restore_contents_and_history(
    tmp_path, monkeypatch, operation, failure_step, after_move, error_type
):
    directory, originals = make_batch(tmp_path)
    history = HistoryManager(tmp_path / "history.json")
    plan = build_rename_plan(find_files(directory), pattern="lower")
    if operation == "undo":
        execute_rename(plan, history)
        expected = {name.lower(): payload for name, payload in originals.items()}
    else:
        expected = originals
    before_history = history.history_file.read_bytes()
    actual_rename = Path.rename
    calls = 0

    def interrupt_once(src, dst):
        nonlocal calls
        calls += 1
        if calls == failure_step and not after_move:
            raise error_type("simulated interruption")
        result = actual_rename(src, dst)
        if calls == failure_step and after_move:
            raise error_type("simulated interruption")
        return result

    monkeypatch.setattr(Path, "rename", interrupt_once)
    with pytest.raises(error_type, match="simulated interruption"):
        if operation == "rename":
            execute_rename(plan, history)
        else:
            execute_undo(history)
    assert_files(directory, expected)
    assert history.history_file.read_bytes() == before_history
    # A retry succeeds after the one-shot fault and does not lose data.
    if operation == "rename":
        execute_rename(plan, history)
        execute_undo(history)
    else:
        execute_undo(history)
    assert_files(directory, originals)


def test_swapped_names_can_be_undone(tmp_path):
    directory, originals = make_batch(tmp_path)
    a, b = directory / "A.txt", directory / "B.txt"
    history = HistoryManager(tmp_path / "history.json")
    execute_rename([RenamePlan(a, b, True), RenamePlan(b, a, True)], history)
    assert_files(directory, {"A.txt": "second payload", "B.txt": "first payload"})
    execute_undo(history)
    assert_files(directory, originals)
    with pytest.raises(ValueError, match="No active transaction"):
        execute_undo(history)


@pytest.mark.parametrize("operation", ["rename", "undo"])
def test_history_save_failure_restores_files(tmp_path, monkeypatch, operation):
    directory, originals = make_batch(tmp_path)
    history = HistoryManager(tmp_path / "history.json")
    plan = build_rename_plan(find_files(directory), pattern="lower")
    if operation == "undo":
        execute_rename(plan, history)
        expected = {name.lower(): payload for name, payload in originals.items()}
    else:
        expected = originals
    before = history.history_file.read_bytes()

    def fail_save(data):
        raise OSError("disk full")

    monkeypatch.setattr(history, "_save", fail_save)
    with pytest.raises(OSError, match="disk full"):
        execute_rename(plan, history) if operation == "rename" else execute_undo(
            history
        )
    assert_files(directory, expected)
    assert history.history_file.read_bytes() == before


def test_renaming_a_symlink_preserves_its_target(tmp_path, monkeypatch):
    directory = tmp_path / "files"
    directory.mkdir()
    target = tmp_path / "target.txt"
    target.write_text("untouched target")
    link = directory / "LINK.txt"
    link.symlink_to(target)
    history = HistoryManager(tmp_path / "history.json")
    monkeypatch.chdir(directory)
    execute_rename(build_rename_plan(find_files(Path(".")), pattern="lower"), history)
    assert (directory / "link.txt").is_symlink()
    assert history.get_latest_active().records[0].src == str(link)
    execute_undo(history)
    assert link.is_symlink()
    assert target.read_text() == "untouched target"


def test_resolved_parent_survives_directory_symlink_retargeting(tmp_path, monkeypatch):
    actual = tmp_path / "actual"
    other = tmp_path / "other"
    actual.mkdir()
    other.mkdir()
    (actual / "A.txt").write_text("original")
    (other / "a.txt").write_text("unrelated")
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    monkeypatch.chdir(tmp_path)
    history = HistoryManager(tmp_path / "history.json")
    execute_rename(
        build_rename_plan(find_files(Path("alias")), pattern="lower"), history
    )
    alias.unlink()
    alias.symlink_to(other, target_is_directory=True)
    execute_undo(history)
    assert_files(actual, {"A.txt": "original"})
    assert_files(other, {"a.txt": "unrelated"})


@pytest.mark.parametrize("bad_history", ["{partial", "{}", "null"])
def test_corrupt_history_is_not_overwritten(tmp_path, bad_history):
    directory, originals = make_batch(tmp_path)
    history = HistoryManager(tmp_path / "history.json")
    history.history_file.write_text(bad_history)
    with pytest.raises(ValueError, match="history"):
        execute_rename(
            build_rename_plan(find_files(directory), pattern="lower"), history
        )
    assert_files(directory, originals)
    assert history.history_file.read_text() == bad_history


def test_recovery_failure_keeps_all_payloads_and_reports_locations(
    tmp_path, monkeypatch
):
    directory, _ = make_batch(tmp_path)
    history = HistoryManager(tmp_path / "history.json")
    plan = build_rename_plan(find_files(directory), pattern="lower")
    actual_rename = Path.rename
    calls = 0

    def fail_move_and_recovery(src, dst):
        nonlocal calls
        calls += 1
        if calls in (3, 4):
            raise OSError("simulated device failure")
        return actual_rename(src, dst)

    monkeypatch.setattr(Path, "rename", fail_move_and_recovery)
    with pytest.raises(RuntimeError, match="retained recovery directories"):
        execute_rename(plan, history)
    assert sorted(p.read_text() for p in directory.rglob("*") if p.is_file()) == [
        "first payload",
        "second payload",
    ]
    assert history.get_latest_active() is None


@pytest.mark.parametrize("operation", ["rename", "undo"])
@pytest.mark.parametrize("error_type", [OSError, KeyboardInterrupt])
def test_interrupt_after_history_replace_keeps_committed_file_state(
    tmp_path, monkeypatch, operation, error_type
):
    import os

    directory, originals = make_batch(tmp_path)
    history = HistoryManager(tmp_path / "history.json")
    plan = build_rename_plan(find_files(directory), pattern="lower")
    if operation == "undo":
        execute_rename(plan, history)
    actual_replace = os.replace

    def replace_then_interrupt(src, dst):
        actual_replace(src, dst)
        raise error_type("interrupted after history commit")

    monkeypatch.setattr(os, "replace", replace_then_interrupt)
    if operation == "rename":
        count, tx_id = execute_rename(plan, history)
        assert count == 2
        assert history.get_latest_active().id == tx_id
        assert_files(
            directory, {name.lower(): payload for name, payload in originals.items()}
        )
    else:
        execute_undo(history)
        assert history.get_latest_active() is None
        assert_files(directory, originals)


def test_unknown_history_outcome_preserves_destination_files(tmp_path, monkeypatch):
    directory, originals = make_batch(tmp_path)
    history = HistoryManager(tmp_path / "history.json")
    plan = build_rename_plan(find_files(directory), pattern="lower")

    def fail_save_and_corrupt(data):
        history.history_file.write_text("unreadable history")
        raise OSError("simulated I/O failure")

    monkeypatch.setattr(history, "_save", fail_save_and_corrupt)
    with pytest.raises(RuntimeError, match="Files remain at their destination paths"):
        execute_rename(plan, history)
    assert_files(
        directory, {name.lower(): payload for name, payload in originals.items()}
    )


@pytest.mark.parametrize("option", ["prefix", "suffix"])
@pytest.mark.parametrize(
    "value", ["../", "nested/", "/absolute/", "..\\", "\\absolute\\", "\x00"]
)
def test_path_components_are_rejected_before_any_moves(tmp_path, option, value):
    directory, originals = make_batch(tmp_path)
    with pytest.raises(ValueError, match="single filename"):
        build_rename_plan(find_files(directory), **{option: value})
    assert_files(directory, originals)


def test_windows_drive_prefix_is_rejected_on_all_platforms(tmp_path):
    directory, originals = make_batch(tmp_path)
    with pytest.raises(ValueError, match="single filename"):
        build_rename_plan(find_files(directory), prefix="C:")
    assert_files(directory, originals)


@pytest.mark.parametrize("alias", ["self", "symlink", "hardlink"])
def test_rename_never_moves_its_history_file(tmp_path, alias):
    directory, originals = make_batch(tmp_path)
    history = HistoryManager(directory / "history.json")
    if alias == "self":
        protected = history.history_file
    elif alias == "symlink":
        protected = directory / "alias.json"
        protected.symlink_to(history.history_file)
    else:
        import os

        protected = directory / "alias.json"
        os.link(history.history_file, protected)
    before_history = history.history_file.read_bytes()
    plan = build_rename_plan([directory / "A.txt", protected], prefix="new_")
    with pytest.raises(ValueError, match="history file"):
        execute_rename(plan, history)
    assert history.history_file.read_bytes() == before_history
    assert protected.exists()
    for name, payload in originals.items():
        assert (directory / name).read_text() == payload
    assert not list(directory.glob("new_*"))
    assert not list(directory.glob(".file-renamer-*"))


def test_legacy_undo_cannot_move_history_file(tmp_path):
    directory, originals = make_batch(tmp_path)
    history = HistoryManager(directory / "history.json")
    history.history_file.write_text(
        json.dumps(
            [
                {
                    "id": "legacy",
                    "timestamp": "then",
                    "records": [
                        {
                            "src": str(directory / "backup.json"),
                            "dst": str(history.history_file),
                        },
                        {
                            "src": str(directory / "old.txt"),
                            "dst": str(directory / "A.txt"),
                        },
                    ],
                }
            ]
        )
    )
    before = history.history_file.read_bytes()
    with pytest.raises(ValueError, match="history file"):
        execute_undo(history)
    assert history.history_file.read_bytes() == before
    for name, payload in originals.items():
        assert (directory / name).read_text() == payload
    assert not (directory / "old.txt").exists()


@pytest.mark.parametrize("name", ["!!!", ".", ".."])
def test_empty_or_dot_transformed_names_are_rejected(tmp_path, name):
    # Path('.') and Path('..') have no ordinary final filename; exercise the
    # transformer through a monkeypatch rather than pretending they are files.
    from unittest.mock import patch

    file = tmp_path / "valid.txt"
    file.write_text("payload")
    transformed = "" if name == "!!!" else name
    with patch("file_renamer.core.transform_filename", return_value=transformed):
        with pytest.raises(ValueError, match="single filename"):
            build_rename_plan([file])
    assert file.read_text() == "payload"


def test_case_only_rename_changes_actual_directory_spelling(tmp_path):
    original = tmp_path / "MiXeD.txt"
    original.write_text("payload")
    history = HistoryManager(tmp_path / "history.json")
    plan = build_rename_plan([original], pattern="lower")
    assert plan[0].has_changed
    count, _ = execute_rename(plan, history)
    assert count == 1
    assert {p.name for p in tmp_path.glob("*.txt")} == {"mixed.txt"}
    execute_undo(history)
    assert {p.name for p in tmp_path.glob("*.txt")} == {"MiXeD.txt"}
    assert original.read_text() == "payload"


def test_windows_path_case_changes_are_not_treated_as_noops():
    from pathlib import PureWindowsPath

    plan = build_rename_plan([PureWindowsPath("C:/files/MiXeD.txt")], pattern="lower")
    assert plan[0].has_changed
    assert plan[0].dst.name == "mixed.txt"


@pytest.mark.parametrize("alias", ["hardlink", "symlink"])
def test_separate_link_entry_cannot_be_overwritten(tmp_path, alias):
    import os

    source, destination = tmp_path / "A.txt", tmp_path / "B.txt"
    source.write_text("payload")
    if alias == "hardlink":
        os.link(source, destination)
    else:
        destination.symlink_to(source)
    history = HistoryManager(tmp_path / "history.json")
    before = history.history_file.read_bytes()
    with pytest.raises(FileExistsError, match="overwrite"):
        execute_rename([RenamePlan(source, destination, True)], history)
    assert source.read_text() == "payload"
    assert destination.read_text() == "payload"
    assert history.history_file.read_bytes() == before
    if alias == "symlink":
        assert destination.is_symlink()


def test_duplicate_source_case_alias_is_rejected_before_staging(tmp_path, monkeypatch):
    import file_renamer.core as core

    source, alias = tmp_path / "A.txt", tmp_path / "a.txt"
    source.write_text("payload")
    history = HistoryManager(tmp_path / "history.json")
    original_exists, original_lstat = core._exists, Path.lstat

    def case_exists(path):
        return str(path) == str(alias) or original_exists(path)

    def case_lstat(path):
        return original_lstat(source if str(path) == str(alias) else path)

    monkeypatch.setattr(core, "_exists", case_exists)
    monkeypatch.setattr(Path, "lstat", case_lstat)
    with pytest.raises(ValueError, match="unique source"):
        execute_rename(
            [
                RenamePlan(source, tmp_path / "first.txt", True),
                RenamePlan(alias, tmp_path / "second.txt", True),
            ],
            history,
        )
    assert source.read_text() == "payload"
    assert history.list_all() == []
    assert not list(tmp_path.glob(".file-renamer-*"))


@pytest.mark.parametrize(
    ("name", "extension", "expected"),
    [
        ("photo.JPG", "jpg", True),
        ("photo.JPG", ".jpg", True),
        ("photo.jpeg", ".jpg", False),
        ("photo.jpgx", ".jpg", False),
        ("photo.jpg.bak", ".jpg", False),
        (".jpg", ".jpg", False),
        ("archive.tar.gz", ".gz", True),
        ("archive.tar.gz", "gz", True),
        ("archive.tar.gz", ".tar.gz", True),
        ("archive.tar.gz", "tar.gz", True),
        ("Archive.TAR.GZ", ".tar.gz", True),
        ("nottar.gz", ".tar.gz", False),
        ("notes.txt", ".tar.gz", False),
        (".env.local", ".local", True),
        ("config.env.local", ".env.local", True),
        (".gitignore", ".gitignore", False),
        ("notes.gitignore", "gitignore", True),
    ],
)
def test_extension_filter_matches_final_and_compound_suffixes(tmp_path, name, extension, expected):
    (tmp_path / name).write_text("x")
    found = find_files(tmp_path, extension=extension)
    assert [path.name for path in found] == ([name] if expected else [])


def test_compound_extension_filter_skips_unrelated_files(tmp_path):
    nested = tmp_path / "sub"
    nested.mkdir()
    (tmp_path / "archive.tar.gz").write_text("gz")
    (tmp_path / "archive.tar.bz2").write_text("bz2")
    (nested / "Photo.JPG").write_text("pic")
    (tmp_path / "notes.txt").write_text("txt")
    assert [path.name for path in find_files(tmp_path, extension=".tar.gz")] == ["archive.tar.gz"]
    assert find_files(tmp_path, recursive=True, extension="JPG") == [nested / "Photo.JPG"]


def test_replace_cannot_escape_the_directory(tmp_path):
    file = tmp_path / "a.txt"
    file.write_text("payload")
    for replacement in ("../a.txt", "..", "", "a/b"):
        with pytest.raises(ValueError, match="single filename"):
            build_rename_plan([file], replacements=[("a.txt", replacement)])
    assert file.read_text() == "payload"
    assert not (tmp_path / "a.txt").is_dir()


def test_preflight_missing_history_does_not_touch_files(tmp_path):
    file = tmp_path / "A.txt"
    file.write_text("x")
    history = tmp_path / "missing-history.json"
    plan = build_rename_plan([file], pattern="lower")
    preflight_rename(plan, history)
    assert plan[0].dst.name == "a.txt"
    assert file.read_text() == "x"
    assert not history.exists()
    assert list(tmp_path.glob(".file-renamer-*")) == []


@pytest.mark.parametrize("occupier", ["directory", "dangling-symlink"])
def test_preflight_rejects_destination_occupied_by_a_non_file(tmp_path, occupier):
    source = tmp_path / "a.txt"
    source.write_text("payload")
    occupied = tmp_path / "pre_a.txt"
    if occupier == "directory":
        occupied.mkdir()
    else:
        occupied.symlink_to("missing-target")
    plan = build_rename_plan([source], prefix="pre_")
    assert plan[0].dst.name == "pre_a.txt"
    history = tmp_path / "history.json"
    with pytest.raises(FileExistsError, match="overwrite"):
        preflight_rename(plan, history)
    assert source.read_text() == "payload"
    assert not history.exists()
    assert list(tmp_path.glob(".file-renamer-*")) == []


def test_preflight_allows_a_rename_chain(tmp_path):
    first = tmp_path / "a.txt"
    second = tmp_path / "pre_a.txt"
    first.write_text("a")
    second.write_text("b")
    history_path = tmp_path / "history.json"
    plan = build_rename_plan(find_files(tmp_path), prefix="pre_")
    preflight_rename(plan, history_path)
    assert {item.dst.name for item in plan} == {"pre_a.txt", "pre_pre_a.txt"}
    assert not history_path.exists()
    history = HistoryManager(history_path)
    execute_rename(plan, history)
    assert not first.exists()
    assert (tmp_path / "pre_a.txt").read_text() == "a"
    assert (tmp_path / "pre_pre_a.txt").read_text() == "b"
    execute_undo(history)
    assert first.read_text() == "a"
    assert second.read_text() == "b"
    assert not (tmp_path / "pre_pre_a.txt").exists()


def test_new_case_colliding_destinations_never_lose_files(tmp_path):
    first, second = tmp_path / "A.txt", tmp_path / "B.txt"
    first.write_text("first")
    second.write_text("second")
    case_sensitive = not (tmp_path / "a.txt").exists()
    history = HistoryManager(tmp_path / "history.json")
    plan = [
        RenamePlan(first, tmp_path / "new.txt", True),
        RenamePlan(second, tmp_path / "NEW.txt", True),
    ]
    if case_sensitive:
        execute_rename(plan, history)
        execute_undo(history)
    else:
        with pytest.raises(FileExistsError):
            execute_rename(plan, history)
        assert history.list_all() == []
    assert first.read_text() == "first"
    assert second.read_text() == "second"
    assert not list(tmp_path.glob(".file-renamer-*"))
