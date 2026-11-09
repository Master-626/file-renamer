# Undo identity validation

Fingerprint and cross-platform fixes validated against main commit
`88ee58acae8346bb89373dc58f8f8b7bcfcea9e3`. Hosted CI results are linked from
the pull request; this report documents the tested behavior and limitations.

## Reproduction

The unmodified baseline passed its existing 87 tests. In a disposable directory,
renaming a file, deleting the renamed fixture, and creating unrelated contents
at the same path caused undo to move the replacement to the original name and
mark the transaction undone. The original deletion was deliberate test setup;
undo did not delete or recover the original contents. The baseline README
already excluded external changes from its guarantees.

## Checks

- 145 tests pass on Python 3.9.25, 3.12.14 and 3.13.5.
- The Python 3.9 run uses minimum declared Click 8.1.0, Rich 13.0.0 and
  pytest 8.0.0 versions.
- Wheel and source distribution build successfully. A fresh Python 3.13
  environment installed the wheel, and all 145 tests passed from outside the
  source checkout with imports verified from site-packages.
- `ruff check --isolated --select E4,E7,E9,F src tests`, byte compilation and
  `git diff --check` pass.

Run the tests with:

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
```

## New regression coverage

- Replacement files are refused, including identical-content replacements with
  copied timestamps but a different file ID.
- Content hashing detects same-size edits with restored modification times and
  simulated reused IDs with different contents.
- Ordinary edits and modification-time changes are refused conservatively.
  Restoring identical bytes and timestamps on the original inode is supported.
- Every batch member is checked before any undo move. Mixed new/legacy records,
  malformed fingerprints and unknown schema versions fail without moving files
  or changing history. A blocked latest batch is not skipped.
- Consecutive rename/undo chains and cyclic swaps preserve fingerprints.
- Multiple hardlinks can be renamed and undone, link-count changes are allowed,
  and edits through another link are refused. Relinking the same inode counts
  as the same file.
- Symlink fingerprints use the link itself, including dangling links and
  directory-target links. Target contents are not read or fingerprinted.
- Raw binary hashing, multi-chunk reads, optional POSIX flags and the Windows
  binary-open flag are covered. The binary flag test is a simulation, not a
  Windows execution test.
- Missing file IDs, unreadable inputs and special file types fail before any
  rename. Observed descriptor substitution and changes during hashing fail.
- Post-move verification errors, interruptions and mismatches roll back within
  the existing batch recovery scope. Original interruption/history-save tests
  continue to pass.
- CLI refusal is nonzero; legacy history remains viewable but not undoable.

## Compatibility and limits

Older absolute-path history without fingerprints can no longer be automatically
undone. No force switch or automatic migration is added. Unreadable files and
filesystems without a usable file ID are refused. Hashing reads regular files
twice during rename and once during undo, increasing runtime for large files.

Hosted CI passes on Ubuntu 22.04 (Python 3.9 and 3.13), macOS 15 (Python
3.13), and Windows 2022 (Python 3.13). Linux/macOS run 145 tests; Windows
runs 144 and skips the unavailable POSIX FIFO test. Symlink tests run on all
three systems. Each job also builds wheel/sdist and checks the CLI entry point.

The first cross-platform runs exposed case-only path comparisons and the
Windows path-stat/fstat ctime discrepancy described in CPython issue #157671.
The fixes preserve exact filename spelling and compare ctime only within the
same stat API, retaining before/after checks. Case-alias detection also requires
readable parent directories. Distinct hardlinks and symlinks remain protected
from overwrites. New case-colliding destinations may be detected during final
moves rather than preflight; rollback protection is tested.
Python file IDs and timestamp behavior vary by filesystem; nonzero IDs are not
a proof of uniqueness. Reused IDs together with identical contents and metadata
cannot be distinguished, and modified history is not authenticated.

Concurrent modification, power loss, forced termination and repeated
interruption during rollback remain outside the guarantee. Keep backups and
preserve any reported recovery directories.
