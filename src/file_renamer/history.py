"""Transaction history tracking for reversible renames."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from file_renamer.identity import FileFingerprint

HISTORY_DIR = Path.home() / ".file_renamer"
HISTORY_FILE = HISTORY_DIR / "history.json"


def absolute_entry_path(path: Path) -> Path:
    """Anchor a directory entry without following a file's own symlink."""
    path = Path(path)
    return path.parent.resolve() / path.name


@dataclass
class RenameRecord:
    src: str
    dst: str
    fingerprint: Optional[FileFingerprint] = None

    @classmethod
    def from_dict(cls, value: dict) -> "RenameRecord":
        data = dict(value)
        if data.get("fingerprint") is not None:
            data["fingerprint"] = FileFingerprint.from_dict(data["fingerprint"])
        return cls(**data)


@dataclass
class Transaction:
    id: str
    timestamp: str
    records: List[RenameRecord]
    undone: bool = False


class HistoryManager:
    """Manages recording and reading batch transactions."""

    def __init__(self, history_file: Optional[Path] = None):
        self.history_file = absolute_entry_path(history_file or HISTORY_FILE)
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_file.exists():
            self._save([])

    def _load(self) -> List[dict]:
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as error:
            raise ValueError(
                f"Cannot read rename history: {self.history_file}"
            ) from error
        if not isinstance(data, list):
            raise ValueError(f"Invalid rename history: {self.history_file}")
        return data

    def _save(self, data: List[dict]) -> None:
        # Replace only a complete, flushed document, leaving old history intact
        # if serialization or writing is interrupted.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.history_file.parent,
                prefix=".history-",
                suffix=".tmp",
                delete=False,
            ) as f:
                temporary = Path(f.name)
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.history_file)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def record_batch(self, operations: List[RenameRecord]) -> Transaction:
        data = self._load()
        tx = Transaction(
            id=f"tx_{int(datetime.now().timestamp())}_{len(data) + 1}",
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            records=[
                RenameRecord(
                    src=str(absolute_entry_path(Path(record.src))),
                    dst=str(absolute_entry_path(Path(record.dst))),
                    fingerprint=record.fingerprint,
                )
                for record in operations
            ],
            undone=False,
        )
        data.append(asdict(tx))
        self._save(data)
        return tx

    def get_latest_active(self) -> Optional[Transaction]:
        """Return the most recent transaction that hasn't been reverted."""
        data = self._load()
        for entry in reversed(data):
            if not entry.get("undone", False):
                records = [RenameRecord.from_dict(r) for r in entry["records"]]
                return Transaction(
                    id=entry["id"],
                    timestamp=entry["timestamp"],
                    records=records,
                    undone=entry.get("undone", False),
                )
        return None

    def mark_undone(self, tx_id: str) -> None:
        data = self._load()
        for entry in data:
            if entry["id"] == tx_id:
                entry["undone"] = True
                break
        self._save(data)

    def list_all(self) -> List[Transaction]:
        data = self._load()
        transactions = []
        for entry in data:
            records = [RenameRecord.from_dict(r) for r in entry.get("records", [])]
            transactions.append(
                Transaction(
                    id=entry["id"],
                    timestamp=entry["timestamp"],
                    records=records,
                    undone=entry.get("undone", False),
                )
            )
        return transactions
