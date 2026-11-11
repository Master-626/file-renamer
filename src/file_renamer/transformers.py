"""Filename transformation logic."""

import re
from typing import Iterable, Optional, Tuple


def split_filename(original_name: str) -> Tuple[str, str]:
    """Return ``(stem, extension)`` for one filename, not a path.

    ``.env`` and ``.gitignore`` have no extension. A leading-dot name with
    another dot, such as ``.env.local``, keeps its last suffix. ``.`` and
    ``..`` stay whole so they cannot be mistaken for an empty stem.
    """
    if original_name in {".", ".."} or "." not in original_name:
        return original_name, ""
    stem, ext = original_name.rsplit(".", 1)
    if stem == "":
        return original_name, ""
    return stem, "." + ext


def apply_replacements(original_name: str, replacements: Optional[Iterable[Tuple[str, str]]]) -> str:
    """Apply literal, case-sensitive replacements in order.

    ``old`` must be non-empty. ``new`` may be empty, which deletes ``old``.
    Metacharacters are not regular expressions.
    """
    if not replacements:
        return original_name
    updated = original_name
    for old, new in replacements:
        if not isinstance(old, str) or not isinstance(new, str):
            raise ValueError("Each replacement must be a pair of strings (old, new).")
        if old == "":
            raise ValueError("The text to replace must not be empty.")
        updated = updated.replace(old, new)
    return updated


def apply_pattern(stem: str, pattern: Optional[str]) -> str:
    """Transform the file stem based on a named pattern."""
    if not pattern:
        return stem

    pat = pattern.lower()
    if pat == "lower":
        return stem.lower()
    if pat == "upper":
        return stem.upper()
    if pat == "title":
        return stem.title()
    if pat == "kebab-spaces":
        return re.sub(r"\s+", "-", stem.strip())
    if pat == "snake-spaces":
        return re.sub(r"\s+", "_", stem.strip())
    if pat == "remove-numbers":
        return re.sub(r"\d+", "", stem)
    if pat == "remove-special":
        # Keep letters, numbers, underscores, and dashes.
        return re.sub(r"[^\w\-]", "", stem)
    raise ValueError(f"Unknown pattern '{pattern}'")


def transform_filename(
    original_name: str,
    pattern: Optional[str] = None,
    prefix: str = "",
    suffix: str = "",
    sequence_num: Optional[int] = None,
    padding: int = 2,
    replacements: Optional[Iterable[Tuple[str, str]]] = None,
) -> str:
    """Generate the target filename given transformation parameters.

    Literal replacements run first, on the whole filename, so they can change
    an extension. The named pattern, sequence, prefix, and suffix then modify
    only the stem and preserve the final suffix.
    """
    original_name = apply_replacements(original_name, replacements)
    stem, ext = split_filename(original_name)

    # Apply named pattern transformation
    new_stem = apply_pattern(stem, pattern)

    # Apply sequential numbering if provided
    if sequence_num is not None:
        num_str = str(sequence_num).zfill(padding)
        new_stem = f"{new_stem}_{num_str}" if new_stem else num_str

    # Apply prefix and suffix
    new_stem = f"{prefix}{new_stem}{suffix}"

    return f"{new_stem}{ext}"
