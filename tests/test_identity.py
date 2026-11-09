"""Undo refuses edited/replaced entries; fixtures are all disposable."""

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

import file_renamer.history as history_module
from file_renamer.cli import cli
from file_renamer.core import (
    RenamePlan,
    build_rename_plan,
    execute_rename,
    execute_undo,
)
from file_renamer.history import HistoryManager
from file_renamer.identity import FileFingerprint, capture_fingerprint


def rename_one(tmp_path, content=b"original bytes"):
    original, renamed = tmp_path / "original.txt", tmp_path / "renamed.txt"
    original.write_bytes(content)
    history = HistoryManager(tmp_path / "history.json")
    execute_rename([RenamePlan(original, renamed, True)], history)
    return original, renamed, history


def assert_refused(original, renamed, history, expected=b"replacement"):
    before = history.history_file.read_bytes()
    for _ in range(2):
        with pytest.raises(ValueError, match="identity or contents changed"):
            execute_undo(history)
        assert not original.exists()
        assert renamed.read_bytes() == expected
        assert history.history_file.read_bytes() == before
        assert not history.list_all()[0].undone


def test_deleted_then_replaced_file_is_not_moved(tmp_path):
    original, renamed, history = rename_one(tmp_path)
    renamed.unlink()
    renamed.write_bytes(b"replacement")
    assert_refused(original, renamed, history)


def test_identical_replacement_is_rejected_by_file_id(tmp_path):
    original, renamed, history = rename_one(tmp_path)
    saved = renamed.stat()
    # Keep the original inode alive, preventing immediate inode reuse.
    renamed.rename(tmp_path / "kept-original.txt")
    renamed.write_bytes(b"original bytes")
    os.utime(renamed, ns=(saved.st_atime_ns, saved.st_mtime_ns))
    assert_refused(original, renamed, history, b"original bytes")


def test_hash_detects_edit_with_same_id_size_and_restored_mtime(tmp_path):
    original, renamed, history = rename_one(tmp_path, b"111111")
    saved = renamed.stat()
    renamed.write_bytes(b"222222")
    os.utime(renamed, ns=(saved.st_atime_ns, saved.st_mtime_ns))
    assert_refused(original, renamed, history, b"222222")


def test_simulated_reused_inode_still_checks_contents(tmp_path, monkeypatch):
    original, renamed, history = rename_one(tmp_path, b"111111")
    old_fingerprint = history.get_latest_active().records[0].fingerprint
    renamed.unlink()
    renamed.write_bytes(b"222222")
    new = capture_fingerprint(renamed)
    replacement_with_reused_metadata = FileFingerprint(
        **{**asdict(old_fingerprint), "sha256": new.sha256}
    )
    monkeypatch.setattr(
        "file_renamer.core.capture_fingerprint",
        lambda path: replacement_with_reused_metadata,
    )
    assert_refused(original, renamed, history, b"222222")


def test_touch_is_conservatively_refused(tmp_path):
    original, renamed, history = rename_one(tmp_path)
    saved = renamed.stat()
    os.utime(renamed, ns=(saved.st_atime_ns, saved.st_mtime_ns + 1_000_000_000))
    assert_refused(original, renamed, history, b"original bytes")


def test_restored_original_contents_and_mtime_can_be_undone(tmp_path):
    original, renamed, history = rename_one(tmp_path)
    saved = renamed.stat()
    renamed.write_bytes(b"temporary edit")
    renamed.write_bytes(b"original bytes")
    os.utime(renamed, ns=(saved.st_atime_ns, saved.st_mtime_ns))
    execute_undo(history)
    assert original.read_bytes() == b"original bytes"


def test_entire_batch_is_checked_before_first_undo_move(tmp_path):
    original, renamed, history = rename_one(tmp_path)
    execute_undo(history)
    other = tmp_path / "other.txt"
    other.write_bytes(b"second")
    execute_rename(build_rename_plan([original, other], prefix="new_"), history)
    (tmp_path / "new_original.txt").write_bytes(b"replacement")
    before = history.history_file.read_bytes()
    with pytest.raises(ValueError, match="identity or contents changed"):
        execute_undo(history)
    assert not original.exists()
    assert not other.exists()
    assert (tmp_path / "new_other.txt").read_bytes() == b"second"
    assert history.history_file.read_bytes() == before


def test_mixed_legacy_and_new_records_refuse_entire_batch(tmp_path):
    files = [tmp_path / "A.txt", tmp_path / "B.txt"]
    for file in files:
        file.write_bytes(file.name.encode())
    history = HistoryManager(tmp_path / "history.json")
    execute_rename(build_rename_plan(files, prefix="new_"), history)
    data = json.loads(history.history_file.read_text())
    del data[0]["records"][0]["fingerprint"]
    history.history_file.write_text(json.dumps(data))
    before = history.history_file.read_bytes()
    with pytest.raises(ValueError, match="without file fingerprints"):
        execute_undo(history)
    assert history.history_file.read_bytes() == before
    for file in files:
        assert not file.exists()
        assert file.with_name("new_" + file.name).read_bytes() == file.name.encode()


def test_two_successive_renames_and_undos_preserve_identity(tmp_path):
    original, renamed, history = rename_one(tmp_path)
    third = tmp_path / "third.txt"
    execute_rename([RenamePlan(renamed, third, True)], history)
    # Reopen history to exercise deserialization, not just in-memory equality.
    execute_undo(HistoryManager(history.history_file))
    execute_undo(HistoryManager(history.history_file))
    assert original.read_bytes() == b"original bytes"
    assert history.get_latest_active() is None


def test_hardlink_count_changes_do_not_invalidate_identity(tmp_path):
    original, renamed, history = rename_one(tmp_path)
    alias = tmp_path / "alias.txt"
    os.link(renamed, alias)
    execute_undo(history)
    assert original.samefile(alias)
    assert original.read_bytes() == b"original bytes"


def test_edit_through_hardlink_is_refused(tmp_path):
    original, renamed, history = rename_one(tmp_path)
    alias = tmp_path / "alias.txt"
    os.link(renamed, alias)
    alias.write_bytes(b"replacement")
    assert_refused(original, renamed, history)


def test_same_inode_relinked_to_destination_remains_same_file(tmp_path):
    original, renamed, history = rename_one(tmp_path)
    alias = tmp_path / "alias.txt"
    os.link(renamed, alias)
    renamed.unlink()
    os.link(alias, renamed)
    execute_undo(history)
    assert original.samefile(alias)


def test_regular_file_replaced_by_symlink_is_refused(tmp_path):
    original, renamed, history = rename_one(tmp_path)
    kept = tmp_path / "kept.txt"
    renamed.rename(kept)
    renamed.symlink_to(kept)
    before = history.history_file.read_bytes()
    with pytest.raises(ValueError, match="identity or contents changed"):
        execute_undo(history)
    assert renamed.is_symlink()
    assert kept.read_bytes() == b"original bytes"
    assert not original.exists()
    assert history.history_file.read_bytes() == before


@pytest.mark.parametrize("dangling", [False, True])
def test_symlink_target_contents_are_not_fingerprinted(tmp_path, dangling):
    target = tmp_path / "target.txt"
    if not dangling:
        target.write_bytes(b"before")
    original, renamed = tmp_path / "link.txt", tmp_path / "new-link.txt"
    original.symlink_to(target)
    history = HistoryManager(tmp_path / "history.json")
    execute_rename([RenamePlan(original, renamed, True)], history)
    target.write_bytes(b"after")
    execute_undo(history)
    assert original.is_symlink()
    assert target.read_bytes() == b"after"


def test_replaced_symlink_is_refused_even_with_same_target(tmp_path):
    target = tmp_path / "target.txt"
    target.write_bytes(b"contents")
    original, renamed = tmp_path / "link.txt", tmp_path / "new-link.txt"
    original.symlink_to(target)
    history = HistoryManager(tmp_path / "history.json")
    execute_rename([RenamePlan(original, renamed, True)], history)
    renamed.rename(tmp_path / "kept-link.txt")
    renamed.symlink_to(target)
    with pytest.raises(ValueError, match="identity or contents changed"):
        execute_undo(history)
    assert renamed.is_symlink()
    assert not original.exists()


def test_fingerprint_hashes_raw_binary_bytes(tmp_path):
    path = tmp_path / "binary.dat"
    payload = b"\r\n\x1a\x00\xff" * 300_000
    path.write_bytes(payload)
    fingerprint = capture_fingerprint(path)
    assert fingerprint.sha256 == hashlib.sha256(payload).hexdigest()
    assert fingerprint.size == len(payload)
    assert FileFingerprint.from_dict(asdict(fingerprint)) == fingerprint


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", 2),
        ("version", True),
        ("inode", 0),
        ("inode", -1),
        ("inode", "123"),
        ("device", -1),
        ("size", -1),
        ("mtime_ns", 1.0),
        ("kind", "directory"),
        ("sha256", "z" * 64),
        ("sha256", "123"),
        ("sha256", None),
        ("unknown_field", 1),
    ],
)
def test_invalid_fingerprint_history_fails_before_moving(tmp_path, field, value):
    original, renamed, history = rename_one(tmp_path)
    data = json.loads(history.history_file.read_text())
    data[0]["records"][0]["fingerprint"][field] = value
    history.history_file.write_text(json.dumps(data))
    before = history.history_file.read_bytes()
    with pytest.raises(ValueError, match="fingerprint"):
        execute_undo(history)
    assert not original.exists()
    assert renamed.read_bytes() == b"original bytes"
    assert history.history_file.read_bytes() == before


@pytest.mark.parametrize("value", [[], "invalid", {}, {"version": 1}])
def test_malformed_fingerprint_is_rejected(value):
    with pytest.raises(ValueError, match="fingerprint"):
        FileFingerprint.from_dict(value)


def test_missing_file_id_refuses_rename_before_any_move(tmp_path, monkeypatch):
    original = tmp_path / "file.txt"
    original.write_bytes(b"contents")
    real_lstat = Path.lstat

    def without_id(path):
        value = real_lstat(path)
        if path == original:
            return SimpleNamespace(st_ino=0, st_dev=value.st_dev)
        return value

    monkeypatch.setattr(Path, "lstat", without_id)
    history = HistoryManager(tmp_path / "history.json")
    with pytest.raises(ValueError, match="usable filesystem file ID"):
        execute_rename(build_rename_plan([original], prefix="new_"), history)
    assert original.read_bytes() == b"contents"
    assert history.list_all() == []


def test_read_failure_leaves_whole_batch_untouched(tmp_path, monkeypatch):
    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    history = HistoryManager(tmp_path / "history.json")
    real_open = os.open

    def fail_second(path, flags, *args, **kwargs):
        if path == second:
            raise PermissionError("unreadable")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", fail_second)
    with pytest.raises(PermissionError, match="unreadable"):
        execute_rename(build_rename_plan([first, second], prefix="new_"), history)
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"
    assert history.list_all() == []


def test_file_modified_during_hash_is_rejected(tmp_path, monkeypatch):
    original = tmp_path / "file.txt"
    original.write_bytes(b"before")
    history = HistoryManager(tmp_path / "history.json")
    actual_read = os.read
    modified = False

    def read_and_modify(descriptor, length):
        nonlocal modified
        chunk = actual_read(descriptor, length)
        if not modified:
            modified = True
            original.write_bytes(b"after, changed size")
        return chunk

    monkeypatch.setattr(os, "read", read_and_modify)
    with pytest.raises(ValueError, match="changed while checking"):
        execute_rename(build_rename_plan([original], prefix="new_"), history)
    assert original.exists()
    assert not (tmp_path / "new_file.txt").exists()
    assert history.list_all() == []


def test_optional_posix_open_flags_are_not_required(tmp_path, monkeypatch):
    path = tmp_path / "file.txt"
    path.write_bytes(b"contents")
    expected = capture_fingerprint(path)
    for name in ("O_NOFOLLOW", "O_NONBLOCK"):
        monkeypatch.delattr(os, name, raising=False)
    assert capture_fingerprint(path) == expected


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation unavailable")
def test_fifo_is_rejected_without_opening_it(tmp_path, monkeypatch):
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="unsupported file type"):
        capture_fingerprint(fifo)


def test_cli_replacement_refusal_and_legacy_history_display(tmp_path, monkeypatch):
    original, renamed, history = rename_one(tmp_path)
    monkeypatch.setattr(history_module, "HISTORY_FILE", history.history_file)
    renamed.write_bytes(b"replacement")
    before = history.history_file.read_bytes()
    result = CliRunner().invoke(cli, ["undo"])
    assert result.exit_code != 0
    assert "identity or contents changed" in result.output
    assert not original.exists()
    assert renamed.read_bytes() == b"replacement"
    assert history.history_file.read_bytes() == before
    data = json.loads(history.history_file.read_text())
    data[0]["records"][0].pop("fingerprint")
    history.history_file.write_text(json.dumps(data))
    result = CliRunner().invoke(cli, ["history"])
    assert result.exit_code == 0, result.output
    result = CliRunner().invoke(cli, ["undo"])
    assert result.exit_code != 0
    assert "without file fingerprints" in result.output


@pytest.mark.parametrize("error_type", [OSError, KeyboardInterrupt])
def test_post_move_fingerprint_failure_rolls_back_entire_batch(
    tmp_path, monkeypatch, error_type
):
    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    history = HistoryManager(tmp_path / "history.json")
    before = history.history_file.read_bytes()
    calls = 0

    def fail_final_verification(path):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise error_type("verification read failed")
        return capture_fingerprint(path)

    monkeypatch.setattr(
        "file_renamer.core.capture_fingerprint", fail_final_verification
    )
    with pytest.raises(error_type, match="verification read failed"):
        execute_rename(build_rename_plan([first, second], prefix="new_"), history)
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"
    assert history.history_file.read_bytes() == before
    assert not list(tmp_path.glob("new_*"))
    assert not list(tmp_path.glob(".file-renamer-*"))


def test_two_hardlinks_can_be_renamed_and_undone_in_one_batch(tmp_path):
    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    first.write_bytes(b"shared contents")
    os.link(first, second)
    history = HistoryManager(tmp_path / "history.json")
    execute_rename(build_rename_plan([first, second], prefix="new_"), history)
    records = history.get_latest_active().records
    assert records[0].fingerprint == records[1].fingerprint
    execute_undo(history)
    assert first.samefile(second)
    assert first.read_bytes() == b"shared contents"


def test_directory_target_symlink_can_be_renamed_and_undone(tmp_path):
    directory = tmp_path / "target-dir"
    directory.mkdir()
    (directory / "child.txt").write_bytes(b"untouched")
    first, second = tmp_path / "link", tmp_path / "new-link"
    first.symlink_to(directory, target_is_directory=True)
    history = HistoryManager(tmp_path / "history.json")
    execute_rename([RenamePlan(first, second, True)], history)
    execute_undo(history)
    assert first.is_symlink()
    assert (directory / "child.txt").read_bytes() == b"untouched"


def test_unknown_latest_fingerprint_does_not_undo_older_batch(tmp_path):
    original, renamed, history = rename_one(tmp_path)
    second = tmp_path / "second.txt"
    second.write_bytes(b"second")
    execute_rename(build_rename_plan([second], prefix="new_"), history)
    data = json.loads(history.history_file.read_text())
    data[-1]["records"][0]["fingerprint"]["version"] = 99
    history.history_file.write_text(json.dumps(data))
    before = history.history_file.read_bytes()
    with pytest.raises(ValueError, match="unsupported file fingerprint"):
        execute_undo(history)
    assert not original.exists()
    assert renamed.read_bytes() == b"original bytes"
    assert (tmp_path / "new_second.txt").read_bytes() == b"second"
    assert not second.exists()
    assert history.history_file.read_bytes() == before


def test_descriptor_substitution_is_rejected_before_reading(tmp_path, monkeypatch):
    original, other = tmp_path / "original", tmp_path / "other"
    original.write_bytes(b"original")
    other.write_bytes(b"other")
    actual_open = os.open

    def open_other(path, flags):
        return actual_open(other, flags)

    monkeypatch.setattr(os, "open", open_other)
    with pytest.raises(ValueError, match="changed while checking"):
        capture_fingerprint(original)
    assert original.read_bytes() == b"original"
    assert other.read_bytes() == b"other"


def test_symlink_replaced_while_reading_is_rejected(tmp_path, monkeypatch):
    link = tmp_path / "link"
    link.symlink_to("original-target")
    actual_readlink = os.readlink

    def replace_after_read(path):
        result = actual_readlink(path)
        link.rename(tmp_path / "kept-link")
        link.symlink_to("replacement-target")
        return result

    monkeypatch.setattr(os, "readlink", replace_after_read)
    with pytest.raises(ValueError, match="changed while checking"):
        capture_fingerprint(link)


def test_post_move_identity_mismatch_rolls_back(tmp_path, monkeypatch):
    original = tmp_path / "original.txt"
    original.write_bytes(b"contents")
    history = HistoryManager(tmp_path / "history.json")
    calls = 0

    def different_final_snapshot(path):
        nonlocal calls
        calls += 1
        fingerprint = capture_fingerprint(path)
        if calls == 2:
            return FileFingerprint(**{**asdict(fingerprint), "sha256": "0" * 64})
        return fingerprint

    monkeypatch.setattr(
        "file_renamer.core.capture_fingerprint", different_final_snapshot
    )
    with pytest.raises(ValueError, match="File changed during rename"):
        execute_rename(build_rename_plan([original], prefix="new_"), history)
    assert original.read_bytes() == b"contents"
    assert not (tmp_path / "new_original.txt").exists()
    assert history.list_all() == []


def test_binary_open_flag_is_used_when_available(tmp_path, monkeypatch):
    path = tmp_path / "file.dat"
    path.write_bytes(b"\r\n\x1a\x00")
    actual_open = os.open
    fake_binary_flag = 1 << 29
    seen = []
    monkeypatch.setattr(
        os, "O_BINARY", fake_binary_flag | getattr(os, "O_BINARY", 0), raising=False
    )

    def record_flags(path, flags):
        seen.append(flags)
        return actual_open(path, flags & ~fake_binary_flag)

    monkeypatch.setattr(os, "open", record_flags)
    fingerprint = capture_fingerprint(path)
    assert all(flags & fake_binary_flag for flags in seen)
    assert fingerprint.sha256 == hashlib.sha256(b"\r\n\x1a\x00").hexdigest()
