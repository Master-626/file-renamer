# Undo safety validation

Validated on Linux on 2026-11-08 against the source at
`7effed7fed91868d7cf3f70a366f806e33f60a35`.

## Automated checks

- 87 tests pass on Python 3.9.25, 3.12.14, and 3.13.5.
- The Python 3.9 run uses the minimum declared Click 8.1.0, Rich 13.0.0,
  and pytest 8.0.0 versions.
- Coverage on Python 3.12: 83% overall, 91% for the rename engine, and 100%
  for history persistence. This is not a claim of complete CLI coverage.
- `ruff check --isolated --select E4,E7,E9,F src tests`, byte compilation,
  and `git diff --check` pass.
- Both wheel and source distribution build successfully with `uv build`.
- A fresh environment installed the wheel and ran the actual CLI from outside
  the source checkout, with a disposable home directory. Renaming in one working
  directory and undoing from another restored only the original files.

Run the test suite with:

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
```

## Regression coverage

- Absolute history remains anchored after changing working directory.
- Legacy relative history is refused without changing files or history; legacy
  absolute history remains supported, including records without `undone`.
- Missing files, occupied destinations, and dangling destination symlinks fail
  before any member of the batch moves.
- Symlink names are renamed without moving their targets. Directory symlink
  aliases are resolved before recording new history.
- Cyclic filename swaps can be undone.
- Rename and undo recover from injected errors and KeyboardInterrupt both before
  and after each move, and successful retry preserves the original contents.
- Failed history writes roll back file moves. An interruption after history has
  already been atomically replaced preserves the committed file state instead.
- Failed rollback retains recovery files and reports their locations. An
  unreadable history commit outcome preserves destination files and tells the
  caller to inspect before retrying.
- A batch cannot move its own history file, including symlink/hard-link aliases
  and legacy undo records that refer to the history path.
- Prefixes/suffixes cannot produce traversal, absolute paths, Windows drive
  prefixes, NUL characters, or empty/dot filenames.
- Dry-run and rejected CLI operations leave files and history untouched.

## Limits

Windows and macOS execution have not been tested locally. The added GitHub
Actions workflow runs the suite on Ubuntu with Python 3.9 and 3.13; remote CI
has not run before publication of this change.

The tool does not lock files or history against other processes. Concurrent
rename/undo or external filesystem/history changes are unsupported. Recovery
from power loss, forced termination, or repeatedly interrupting rollback is not
guaranteed. Keep backups and preserve any reported recovery directories.
