# file-renamer

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CLI Tool](https://img.shields.io/badge/CLI-Tool-green.svg)]()

A fast, production-grade CLI utility for batch renaming files. Features rich terminal outputs, dry-run safety checks, recursive directory scanning, and a complete transaction-based undo history.

## ✨ Features

- **Built-in Transformations**: Lowercase, uppercase, title case, space replacement, prefix/suffix, sequential numbering, remove numbers, and remove special characters.
- **Safety First**: Dry-run preview (`--dry-run`) enabled on all mutating commands.
- **Collision Protection**: Checks for existing target files or conflicting target names before executing.
- **Undo History**: Transactional rollbacks. Undo your last operation with a single command or view historical batches.
- **Filtering**: Target specific extensions (e.g., `--ext .png`) and recursively traverse directories (`-r/--recursive`).
- **Terminal UI**: Visual side-by-side previews with colors and tables powered by Rich.

---

## 📦 Installation

```bash
git clone https://github.com/Master-626/file-renamer.git
cd file-renamer
pip install .
```

## 🚀 Quick Start

### 1. View Available Patterns
```bash
file-renamer patterns
```

### 2. Preview Files in a Directory
```bash
file-renamer list ./photos --ext .jpg -r
```

### 3. Dry-Run Rename (Always preview first!)
```bash
file-renamer rename ./photos --pattern lower --prefix "vacation_" --dry-run
```

### 4. Execute Rename
```bash
file-renamer rename ./photos --pattern lower --prefix "vacation_"
```

### 5. Undo Operations
```bash
# Inspect history
file-renamer history

# Revert the latest batch
file-renamer undo
```

## 📖 Command Reference

### `file-renamer rename`
```bash
file-renamer rename [DIRECTORY] [OPTIONS]
```

**Options:**
- `-p, --pattern`: Choose from `lower`, `upper`, `title`, `kebab-spaces`, `snake-spaces`, `remove-numbers`, `remove-special`.
- `--prefix TEXT`: Prepend a string to filenames.
- `--suffix TEXT`: Append a string to filenames (before extension).
- `--sequence`: Add sequential numbers (1, 2, ...).
- `--start INT`: Sequential numbering start index (default: 1).
- `--padding INT`: Zero-padding width for sequence (default: 2).
- `-e, --ext TEXT`: Filter by file extension (e.g., `.txt` or `txt`).
- `-r, --recursive`: Recursively traverse directories.
- `-d, --dry-run`: Preview changes without renaming.

### `file-renamer undo`
Reverts the operations in the latest transaction batch.

### `file-renamer history`
Displays a table of previous rename batches and their current revert status.

## 🧪 Testing

```bash
pip install -e ".[dev]"
pytest
```

## 📄 License

MIT License


## Undo safety and existing history

New batches record absolute paths, so `file-renamer undo` can be run from a
different working directory without touching similarly named files there.
Directory symlinks are resolved when recording a batch; file symlinks themselves
are renamed rather than their targets.

History created by older versions may contain relative paths with no record of
the original working directory. Automatic undo **refuses the entire batch** if
any source or destination is relative, leaving both files and history unchanged.
Inspect `~/.file_renamer/history.json` and restore those names manually only after
verifying their original directory. Do not guess the directory from matching
filenames or replace history paths just to bypass this check. Older histories with
absolute paths remain readable, but automatic undo now also requires the file
fingerprints described below.

Transformed names must be single filenames; path separators and drive prefixes
are rejected. Rename and undo refuse to move the history file or its aliases.

Rename and undo validate the whole batch before moving files, stage cyclic
renames safely, and attempt rollback if a move or history write fails, including
Ctrl-C. History is written with an atomic replacement; unreadable history causes
an error instead of being silently discarded. If rollback itself fails, the error
reports recovery directories. Keep their contents and inspect the original and
final paths before retrying.

These safeguards are not a substitute for backups. They do not provide recovery
from power loss or forced process termination, and concurrent rename/undo
processes or external changes to the same files/history are not supported.


## File identity checks before undo

New rename batches save a versioned fingerprint for every entry: filesystem
file ID and device, entry type, size, modification time, and SHA-256. Regular
files are read in chunks; symlinks record the link target text, not the target's
contents. Every source is checked before renaming, and every destination is
checked again before history is saved. Undo checks the entire batch before it
moves any entry.

If a fingerprint differs because a file was replaced, edited, or has a different
modification time, automatic undo refuses the whole batch and leaves files and
history unchanged. This is
intentionally conservative: ordinary in-place edits and editors that replace
files on save are both refused. Undo restores names, not file contents. A failed
check cannot recover an original file deleted outside this tool. Inspect the
files and history and restore names manually if appropriate; there is no force
option or automatic history upgrade.

**Compatibility change:** older history without fingerprints is still readable
with `file-renamer history`, including absolute-path records from the earlier
path-safety fix, but is no longer automatically undoable. Missing or unsupported
fingerprints are not inferred from whatever file currently occupies the path.
A blocked latest batch is never skipped in favor of undoing an older batch.

Changes to a symlink's target contents do not change the link's fingerprint.
Additional hard links are allowed; edits through any hard link are detected.
Relinking the same inode counts as the same file. Access time, permission bits,
link count, and change time are not persisted in the fingerprint, so our own
rename/undo operations do not invalidate earlier batches.

Hashing reads each regular file twice during rename and once during undo, which
can be slow for large files. Unreadable files and filesystems without a usable
file ID are refused even when directory permissions would allow a rename.
Only regular files and symlinks are supported. Parent directories must also be
readable so case-insensitive aliases can be distinguished from separate entries.
Case-only renames preserve the requested directory spelling on supported
filesystems. Collisions between two previously nonexistent names that differ
only by case may be caught during final moves; rollback then restores the batch.

These checks are evidence, not a perfect identity guarantee. Filesystems may
reuse or misreport file IDs, and a replacement with the same ID, contents and
metadata cannot be distinguished. Fingerprints do not authenticate a modified
history file. Concurrent modifications can still happen between checking and
moving; no concurrent-swap, forced-termination or power-loss guarantee is added.
The implementation uses Python's filesystem IDs and binary reads, with optional
no-follow/nonblocking open flags where available. CI exercises Linux, Windows
and macOS. Network and unusual filesystem behavior still need their own
validation before relying on these checks there.
