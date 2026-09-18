"""Filename transformation logic."""

import re
from typing import Optional


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
        # Keep alphanumeric, dashes, and underscores
        return re.sub(r"[^\w\-]", "", stem)
    raise ValueError(f"Unknown pattern '{pattern}'")


def transform_filename(
    original_name: str,
    pattern: Optional[str] = None,
    prefix: str = "",
    suffix: str = "",
    sequence_num: Optional[int] = None,
    padding: int = 2,
) -> str:
    """Generate the target filename given transformation parameters.
    
    Preserves file extension and modifies only the stem.
    """
    if "." in original_name and not original_name.startswith("."):
        parts = original_name.rsplit(".", 1)
        stem, ext = parts[0], "." + parts[1]
    else:
        # Handles files with no extension or hidden dotfiles (e.g., .env)
        stem = original_name
        ext = ""

    # Apply named pattern transformation
    new_stem = apply_pattern(stem, pattern)

    # Apply sequential numbering if provided
    if sequence_num is not None:
        num_str = str(sequence_num).zfill(padding)
        new_stem = f"{new_stem}_{num_str}" if new_stem else num_str

    # Apply prefix and suffix
    new_stem = f"{prefix}{new_stem}{suffix}"

    return f"{new_stem}{ext}"
