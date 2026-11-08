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
filenames or replace history paths just to bypass this check. Older history with
absolute paths remains supported.

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
