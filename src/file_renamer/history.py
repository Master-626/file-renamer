"""Transaction history tracking for reversible renames."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

HISTORY_DIR = Path.home() / ".file_renamer"
HISTORY_FILE = HISTORY_DIR / "history.json"


@dataclass
class RenameRecord:
    src: str
    dst: str


@dataclass
class Transaction:
    id: str
    timestamp: str
    records: List[RenameRecord]
    undone: bool = False


class HistoryManager:
    """Manages recording and reading batch transactions."""

    def __init__(self, history_file: Optional[Path] = None):
        self.history_file = history_file or HISTORY_FILE
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_file.exists():
            self._save([])

    def _load(self) -> List[dict]:
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, data: List[dict]) -> None:
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def record_batch(self, operations: List[RenameRecord]) -> Transaction:
        data = self._load()
        tx = Transaction(
            id=f"tx_{int(datetime.now().timestamp())}_{len(data) + 1}",
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            records=operations,
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
                records = [RenameRecord(**r) for r in entry["records"]]
                return Transaction(
                    id=entry["id"],
                    timestamp=entry["timestamp"],
                    records=records,
                    undone=entry["undone"],
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
            records = [RenameRecord(**r) for r in entry.get("records", [])]
            transactions.append(
                Transaction(
                    id=entry["id"],
                    timestamp=entry["timestamp"],
                    records=records,
                    undone=entry.get("undone", False),
                )
            )
        return transactions
