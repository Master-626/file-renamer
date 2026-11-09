"""Conservative evidence that an entry still matches a recorded rename.

These fingerprints detect ordinary replacements and edits, not hostile races or
filesystems that recycle identifiers together with matching contents/metadata.
"""

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileFingerprint:
    version: int
    kind: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    sha256: str

    @classmethod
    def from_dict(cls, value: Any) -> "FileFingerprint":
        if not isinstance(value, dict):
            raise ValueError("Invalid file fingerprint in rename history.")
        try:
            fingerprint = cls(**value)
        except TypeError as error:
            raise ValueError("Invalid file fingerprint in rename history.") from error
        numbers = (
            fingerprint.version,
            fingerprint.device,
            fingerprint.inode,
            fingerprint.size,
            fingerprint.mtime_ns,
        )
        if (
            any(type(number) is not int for number in numbers)
            or fingerprint.version != 1
            or fingerprint.kind not in ("file", "symlink")
            or fingerprint.device < 0
            or fingerprint.inode <= 0
            or fingerprint.size < 0
            or not isinstance(fingerprint.sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", fingerprint.sha256) is None
        ):
            raise ValueError(
                "Invalid or unsupported file fingerprint in rename history."
            )
        return fingerprint


def _stat_signature(value: os.stat_result) -> tuple:
    # ctime is useful while taking one snapshot, but is deliberately NOT saved:
    # our own renames change it and would invalidate successive undo operations.
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def capture_fingerprint(path: Path) -> FileFingerprint:
    """Read a consistent snapshot without following a symlink's target."""
    before = path.lstat()
    if before.st_ino <= 0 or before.st_dev < 0:
        raise ValueError(f"Cannot verify a usable filesystem file ID for: {path}")
    digest = hashlib.sha256()
    if stat.S_ISLNK(before.st_mode):
        kind = "symlink"
        digest.update(os.fsencode(os.readlink(path)))
    elif stat.S_ISREG(before.st_mode):
        kind = "file"
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        try:
            if _stat_signature(os.fstat(descriptor)) != _stat_signature(before):
                raise ValueError(f"File changed while checking its identity: {path}")
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            if _stat_signature(os.fstat(descriptor)) != _stat_signature(before):
                raise ValueError(f"File changed while checking its identity: {path}")
        finally:
            os.close(descriptor)
    else:
        raise ValueError(f"Cannot fingerprint unsupported file type: {path}")
    if _stat_signature(path.lstat()) != _stat_signature(before):
        raise ValueError(f"File changed while checking its identity: {path}")
    return FileFingerprint(
        version=1,
        kind=kind,
        device=before.st_dev,
        inode=before.st_ino,
        size=before.st_size,
        mtime_ns=before.st_mtime_ns,
        sha256=digest.hexdigest(),
    )
