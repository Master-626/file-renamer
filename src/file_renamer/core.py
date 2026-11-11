"""Core renaming engine and filesystem operations."""

import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterable, List, Optional, Tuple

from file_renamer.history import HistoryManager, RenameRecord, absolute_entry_path
from file_renamer.identity import capture_fingerprint
from file_renamer.transformers import transform_filename


@dataclass
class RenamePlan:
    src: Path
    dst: Path
    has_changed: bool


def _normalize_extension(extension: str) -> str:
    ext = extension.lower()
    if not ext.startswith("."):
        ext = "." + ext
    return ext


def _matches_extension(path: Path, ext: str) -> bool:
    """Match a final suffix, or a compound suffix such as ``.tar.gz``.

    One-dot filters stay aligned with ``Path.suffix``, so ``.jpg`` does not
    match ``.jpeg`` or a file named ``.jpg``. Filters with more than one dot
    match the end of the filename when a non-empty stem remains.
    """
    if path.suffix.lower() == ext:
        return True
    if ext.count(".") < 2:
        return False
    name = path.name.lower()
    return len(name) > len(ext) and name.endswith(ext)


def find_files(
    directory: Path,
    recursive: bool = False,
    extension: Optional[str] = None,
) -> List[Path]:
    """Retrieve files in directory, optionally filtered and recursive."""
    if not directory.exists() or not directory.is_dir():
        raise FileNotFoundError(f"Directory '{directory}' does not exist.")

    iterator: Iterable[Path] = (
        directory.rglob("*") if recursive else directory.iterdir()
    )
    files = [p for p in iterator if p.is_file()]

    if extension:
        ext = _normalize_extension(extension)
        files = [p for p in files if _matches_extension(p, ext)]

    return sorted(files)


def build_rename_plan(
    files: List[Path],
    pattern: Optional[str] = None,
    prefix: str = "",
    suffix: str = "",
    sequence: bool = False,
    start: int = 1,
    padding: int = 2,
    replacements: Optional[Iterable[Tuple[str, str]]] = None,
) -> List[RenamePlan]:
    """Generate mapping of source to destination paths and validate collisions."""
    plan: List[RenamePlan] = []
    seen_destinations = set()

    for idx, file_path in enumerate(files):
        seq_val = (start + idx) if sequence else None
        new_name = transform_filename(
            original_name=file_path.name,
            pattern=pattern,
            prefix=prefix,
            suffix=suffix,
            sequence_num=seq_val,
            padding=padding,
            replacements=replacements,
        )
        if (
            new_name in ("", ".", "..")
            or any(character in new_name for character in ("/", "\\", "\0"))
            or PureWindowsPath(new_name).drive
        ):
            raise ValueError(
                f"Transformation must produce a single filename, not a path: {new_name!r}"
            )
        dst_path = file_path.parent / new_name

        if dst_path in seen_destinations:
            raise ValueError(f"Collision detected: Multiple files map to {dst_path}")
        seen_destinations.add(dst_path)

        plan.append(
            RenamePlan(
                src=file_path,
                dst=dst_path,
                has_changed=(str(file_path) != str(dst_path)),
            )
        )

    return plan


def _exists(path: Path) -> bool:
    """Include broken symlinks when checking for occupied names."""
    return os.path.lexists(path)


def _entry_key(path: Path, directory_names: dict) -> tuple:
    """Identify case aliases without conflating distinct hardlink entries."""
    names = directory_names.setdefault(path.parent, None)
    if names is None:
        names = {entry.name for entry in path.parent.iterdir()}
        directory_names[path.parent] = names
    parent_stat = path.parent.stat()
    if parent_stat.st_ino <= 0:
        raise ValueError(f"Cannot verify a usable directory file ID for: {path.parent}")
    name = path.name
    if name not in names and _exists(path):
        entry_stat = path.lstat()
        for candidate in names:
            if candidate.casefold() != name.casefold():
                continue
            candidate_stat = (path.parent / candidate).lstat()
            if (
                entry_stat.st_ino > 0
                and stat.S_IFMT(entry_stat.st_mode)
                == stat.S_IFMT(candidate_stat.st_mode)
                and os.path.samestat(entry_stat, candidate_stat)
            ):
                name = candidate
                break
    return parent_stat.st_dev, parent_stat.st_ino, name


def _validate_moves(moves: List[Tuple[Path, Path]], history_file: Path) -> None:
    directory_names = {}
    sources = {_entry_key(src, directory_names) for src, _ in moves}
    destinations = {_entry_key(dst, directory_names) for _, dst in moves}
    if len(sources) != len(moves) or len(destinations) != len(moves):
        raise ValueError("A batch must have unique source and destination paths.")
    for src, dst in moves:
        for path in (src, dst):
            # samefile() raises FileNotFoundError when history does not exist yet.
            # Dry-run preflight runs before that file is created.
            if absolute_entry_path(path) == history_file or (
                path.exists()
                and history_file.exists()
                and path.samefile(history_file)
            ):
                raise ValueError(
                    f"Cannot rename the history file or its aliases: {path}"
                )
        if not _exists(src):
            raise FileNotFoundError(f"Missing file: {src}")
        if src.is_dir() and not src.is_symlink():
            raise ValueError(f"Cannot rename a directory: {src}")
        if not dst.parent.is_dir():
            raise FileNotFoundError(f"Missing destination directory: {dst.parent}")
        if _exists(dst) and _entry_key(dst, directory_names) not in sources:
            raise FileExistsError(f"Cannot overwrite existing file: {dst}")


def _move_to_empty(src: Path, dst: Path) -> None:
    if _exists(dst):
        raise FileExistsError(f"Cannot overwrite existing file: {dst}")
    src.rename(dst)


def _apply_moves(
    moves: List[Tuple[Path, Path]],
    save_history: Callable[[], None],
    history_committed: Callable[[], bool],
    history_file: Path,
) -> None:
    """Stage a whole batch and roll it back on errors, including Ctrl-C.

    This protects against ordinary failures, not process termination or another
    process concurrently changing the same files. Recovery files are retained
    and reported if a rollback itself fails.
    """
    _validate_moves(moves, history_file)
    stages: List[Tuple[Path, Path, Path]] = []
    final_started: List[Tuple[Path, Path]] = []
    saving_history = False
    try:
        for src, dst in moves:
            stage_dir = Path(tempfile.mkdtemp(prefix=".file-renamer-", dir=src.parent))
            staged = stage_dir / src.name
            # Record the location before moving, so an interrupt immediately
            # after a successful rename can still be recovered.
            stages.append((src, staged, dst))
            _move_to_empty(src, staged)
        for _, staged, dst in stages:
            final_started.append((staged, dst))
            _move_to_empty(staged, dst)
        saving_history = True
        save_history()
    except BaseException as error:
        if saving_history:
            # An interrupt can arrive after os.replace committed the history.
            # Do not roll back files against a successfully committed record.
            try:
                committed = history_committed()
            except Exception as verification_error:
                raise RuntimeError(
                    "Files remain at their destination paths, but history could "
                    "not be verified. Inspect files and history before retrying."
                ) from verification_error
            if committed:
                return
        recovery_errors = []
        # Return completed final moves to staging before restoring any source.
        # This also supports swaps/cycles without overwriting other batch files.
        for staged, dst in reversed(final_started):
            if not _exists(staged) and _exists(dst):
                try:
                    _move_to_empty(dst, staged)
                except OSError as recovery_error:
                    recovery_errors.append(str(recovery_error))
        for src, staged, _ in stages:
            if _exists(staged):
                try:
                    _move_to_empty(staged, src)
                except OSError as recovery_error:
                    recovery_errors.append(str(recovery_error))
        if recovery_errors:
            locations = ", ".join(str(staged.parent) for _, staged, _ in stages)
            raise RuntimeError(
                "Batch failed and could not be fully restored. Do not retry "
                f"blindly; retained recovery directories: {locations}. "
                + "; ".join(recovery_errors)
            ) from error
        raise
    finally:
        for _, staged, _ in stages:
            try:
                staged.parent.rmdir()  # Never delete a retained recovery file.
            except OSError:
                pass


def rename_moves(plan: List[RenamePlan]) -> List[Tuple[Path, Path]]:
    """Absolute moves for entries whose anchored path actually changes."""
    moves = [
        (absolute_entry_path(item.src), absolute_entry_path(item.dst))
        for item in plan
        if item.has_changed
    ]
    return [(src, dst) for src, dst in moves if str(src) != str(dst)]


def preflight_rename(plan: List[RenamePlan], history_file: Path) -> None:
    """Raise the same path and collision errors as execution, without writing.

    Does not create the history file, stage files, or hash contents.
    """
    _validate_moves(rename_moves(plan), absolute_entry_path(history_file))


def execute_rename(
    plan: List[RenamePlan],
    history_mgr: Optional[HistoryManager] = None,
) -> Tuple[int, Optional[str]]:
    """Execute the rename plan, returning renamed count and transaction ID."""
    history = history_mgr or HistoryManager()
    moves = rename_moves(plan)
    if not moves:
        return 0, None
    # Refuse unreadable history before touching any files.
    existing_ids = {tx.id for tx in history.list_all()}
    _validate_moves(moves, history.history_file)
    # Capture all identities before moving anything; a read/identity failure
    # must leave the entire batch untouched.
    records = [
        RenameRecord(src=str(src), dst=str(dst), fingerprint=capture_fingerprint(src))
        for src, dst in moves
    ]
    tx_id = None

    def save_history() -> None:
        nonlocal tx_id
        for record in records:
            if capture_fingerprint(Path(record.dst)) != record.fingerprint:
                raise ValueError(
                    f"File changed during rename; history was not saved: {record.dst}"
                )
        tx_id = history.record_batch(records).id

    def history_committed() -> bool:
        nonlocal tx_id
        for tx in history.list_all():
            if tx.id not in existing_ids and tx.records == records and not tx.undone:
                tx_id = tx.id
                return True
        return False

    _apply_moves(moves, save_history, history_committed, history.history_file)
    return len(records), tx_id


def execute_undo(
    history_mgr: Optional[HistoryManager] = None,
) -> Tuple[str, List[Tuple[str, str]]]:
    """Revert the latest batch without interpreting legacy paths against cwd."""
    history = history_mgr or HistoryManager()
    latest_tx = history.get_latest_active()
    if not latest_tx:
        raise ValueError("No active transaction found to undo.")

    # Old relative histories have no trustworthy base directory. Never guess,
    # even when matching filenames happen to exist in the current directory.
    if any(
        not Path(rec.src).is_absolute() or not Path(rec.dst).is_absolute()
        for rec in latest_tx.records
    ):
        raise ValueError(
            "Cannot safely undo legacy history containing relative paths. "
            "No files were changed. Restore these files manually after "
            "verifying their original directory; keep the history for reference."
        )

    reverted = [(rec.dst, rec.src) for rec in reversed(latest_tx.records)]
    moves = [(Path(src), Path(dst)) for src, dst in reverted]
    _validate_moves(moves, history.history_file)

    if any(rec.fingerprint is None for rec in latest_tx.records):
        raise ValueError(
            "Cannot safely undo legacy history without file fingerprints. "
            "No files were changed. Verify the files and restore names manually; "
            "keep the history for reference."
        )
    # Validate the entire batch before moving any entry. In-place edits are
    # intentionally refused too: matching pathnames alone are not sufficient.
    for rec in latest_tx.records:
        if capture_fingerprint(Path(rec.dst)) != rec.fingerprint:
            raise ValueError(
                f"Cannot safely undo: file identity or contents changed: {rec.dst}. "
                "No files were changed. Inspect files and history before retrying."
            )

    def history_committed() -> bool:
        return any(tx.id == latest_tx.id and tx.undone for tx in history.list_all())

    _apply_moves(
        moves,
        lambda: history.mark_undone(latest_tx.id),
        history_committed,
        history.history_file,
    )
    return latest_tx.id, reverted
