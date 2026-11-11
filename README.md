# file-renamer

## 中文简介

`file-renamer` 是一个可撤销的批量重命名命令行工具。它能对文件名做大小写、空格替换、去数字、去特殊字符、前缀、后缀和序号处理，也可用重复的 `--replace OLD NEW` 做区分大小写的字面替换。字面替换最先执行，因此可以改扩展名；随后的模式、序号、前缀和后缀只改主文件名，并保留最后一段扩展名（`.env.local` 会保留 `.local`，`.env` 和 `.gitignore` 没有扩展名）。

`--dry-run` 只预览，不写文件、也不写历史，但会做与正式执行相同的路径和冲突检查。目标已存在、名字不是单个文件名，或会动到历史文件时，预览会失败并保持目录不变。`--ext .tar.gz` 这类复合扩展名可以用来过滤。撤销会核对文件指纹；内容或身份变了就会整批拒绝。

```bash
pip install -e ".[dev]"
ruff check src tests
pytest
```

下文是完整英文说明。

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CLI Tool](https://img.shields.io/badge/CLI-Tool-green.svg)]()

Batch-rename files from the terminal. The command shows a preview, refuses names that would leave the directory or overwrite an unrelated entry, and records each batch so it can be undone.

## ✨ Features

- **Built-in Transformations**: Lowercase, uppercase, title case, space replacement, prefix/suffix, sequential numbering, remove numbers, and remove special characters. Patterns change the stem and keep the final suffix (`FILE NAME.txt`, not `FILE NAME.TXT`).
- **Literal replace**: Repeatable `--replace OLD NEW`, applied to the original filename before those transforms. `OLD` is literal text, not a regular expression, and `NEW` may be empty.
- **Safety First**: `--dry-run` prints the plan and runs the same path and collision checks as a real rename, without writing files or history.
- **Collision Protection**: Refuses an existing target unless that entry is itself being renamed away in the same batch. Two files that map to one new name are also refused.
- **Undo History**: Transactional rollbacks. Undo your last operation with a single command or view historical batches.
- **Filtering**: Target an extension (`--ext .png`, `png`, or a compound suffix such as `--ext .tar.gz`) and recursively traverse directories (`-r/--recursive`).
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

### 5. Literal replace, then undo
`--replace` runs before `--pattern`, so the extension can change and the stem is still normalized:

```bash
file-renamer rename ./photos --replace IMG_ vacation_ --replace .JPEG .jpg --pattern lower --dry-run
file-renamer rename ./photos --replace IMG_ vacation_ --replace .JPEG .jpg --pattern lower
file-renamer undo
```

### 6. Undo Operations
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
- `-p, --pattern`: Choose from `lower`, `upper`, `title`, `kebab-spaces`, `snake-spaces`, `remove-numbers`, `remove-special`. The pattern changes the stem only. `upper` turns `file name.txt` into `FILE NAME.txt`.
- `--prefix TEXT`: Prepend a string to the stem.
- `--suffix TEXT`: Append a string to the stem, before the extension. `.env.local` becomes `.env_bak.local` with `--suffix _bak`; `.gitignore` has no extension, so the same suffix becomes `.gitignore_bak`.
- `--replace OLD NEW`: Replace every literal occurrence of `OLD` with `NEW` in the original filename. Repeat the option to apply several pairs, in order. `OLD` is case-sensitive and must not be empty. An empty `NEW` deletes `OLD`. This step runs before `--pattern`, so it can change the extension. A result that contains a path separator, a drive prefix, or is empty, `.`, or `..` is rejected.
- `--sequence`: Add sequential numbers (1, 2, ...) in sorted path order, across the whole selection.
- `--start INT`: Sequential numbering start index (default: 1). Ignored unless `--sequence` is set.
- `--padding INT`: Zero-padding width for sequence (default: 2).
- `-e, --ext TEXT`: Keep files whose final suffix matches (`.txt` or `txt`). A filter with more than one dot, such as `.tar.gz`, matches that compound suffix. Matching is case-insensitive. `.jpg` does not match `.jpeg` or a file named `.jpg`.
- `-r, --recursive`: Recursively traverse directories. The preview shows paths relative to the directory you passed, so nested files with the same filename stay distinct.
- `-d, --dry-run`: Print the plan and run collision, path, and history-file checks without renaming and without creating history. It does not hash file contents; a later real run still does.

### `file-renamer undo`
Reverts the operations in the latest transaction batch.

### `file-renamer history`
Displays a table of previous rename batches and their current revert status.

## 🧪 Testing

Development installs include pytest and Ruff. The commands below are the same checks GitHub Actions runs. CI tests Python 3.9 through 3.13 on Ubuntu 22.04, plus Python 3.13 on Windows and macOS, then builds the package and runs `file-renamer --help`.

```bash
pip install -e ".[dev]"
ruff check src tests
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
