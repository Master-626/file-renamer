"""Core renaming engine and filesystem operations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from file_renamer.history import HistoryManager, RenameRecord
from file_renamer.transformers import transform_filename


@dataclass
class RenamePlan:
    src: Path
    dst: Path
    has_changed: bool


def find_files(
    directory: Path,
    recursive: bool = False,
    extension: Optional[str] = None,
) -> List[Path]:
    """Retrieve files in directory, optionally filtered and recursive."""
    if not directory.exists() or not directory.is_dir():
        raise FileNotFoundError(f"Directory '{directory}' does not exist.")

    iterator: Iterable[Path] = directory.rglob("*") if recursive else directory.iterdir()
    files = [p for p in iterator if p.is_file()]

    if extension:
        ext = extension.lower()
        if not ext.startswith("."):
            ext = "." + ext
        files = [p for p in files if p.suffix.lower() == ext]

    return sorted(files)


def build_rename_plan(
    files: List[Path],
    pattern: Optional[str] = None,
    prefix: str = "",
    suffix: str = "",
    sequence: bool = False,
    start: int = 1,
    padding: int = 2,
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
        )
        dst_path = file_path.parent / new_name

        if dst_path in seen_destinations:
            raise ValueError(f"Collision detected: Multiple files map to {dst_path}")
        seen_destinations.add(dst_path)

        plan.append(
            RenamePlan(
                src=file_path,
                dst=dst_path,
                has_changed=(file_path != dst_path),
            )
        )

    return plan


def execute_rename(
    plan: List[RenamePlan],
    history_mgr: Optional[HistoryManager] = None,
) -> Tuple[int, Optional[str]]:
    """Execute the rename plan, returning renamed count and transaction ID."""
    history = history_mgr or HistoryManager()
    records: List[RenameRecord] = []
    
    # Check for file overwriting existing non-participating files
    for item in plan:
        if item.has_changed and item.dst.exists() and item.dst not in [p.src for p in plan]:
            raise FileExistsError(f"Cannot overwrite existing file: {item.dst}")

    # Temporary naming pass to avoid cyclic renaming conflicts (e.g., A -> B, B -> A)
    staging_map: List[Tuple[Path, Path]] = []
    for item in plan:
        if item.has_changed:
            tmp_dst = item.src.parent / f".tmp_{item.src.name}_{id(item)}"
            item.src.rename(tmp_dst)
            staging_map.append((tmp_dst, item.dst))
            records.append(RenameRecord(src=str(item.src), dst=str(item.dst)))

    # Move from stage to final destination
    for tmp_dst, final_dst in staging_map:
        tmp_dst.rename(final_dst)

    tx_id = None
    if records:
        tx = history.record_batch(records)
        tx_id = tx.id

    return len(records), tx_id


def execute_undo(
    history_mgr: Optional[HistoryManager] = None,
) -> Tuple[str, List[Tuple[str, str]]]:
    """Reverts the last applied rename transaction."""
    history = history_mgr or HistoryManager()
    latest_tx = history.get_latest_active()

    if not latest_tx:
        raise ValueError("No active transaction found to undo.")

    reverted: List[Tuple[str, str]] = []
    # Reverse order execution prevents ordering collisions
    for rec in reversed(latest_tx.records):
        src_path = Path(rec.dst)  # Current file on disk
        target_path = Path(rec.src)  # File destination upon undo

        if not src_path.exists():
            raise FileNotFoundError(f"Missing file during undo: {src_path}")
        if target_path.exists():
            raise FileExistsError(f"Target already exists during undo: {target_path}")

        src_path.rename(target_path)
        reverted.append((rec.dst, rec.src))

    history.mark_undone(latest_tx.id)
    return latest_tx.id, reverted
