"""Tests for naming pattern transformers."""

import pytest
from file_renamer.transformers import apply_pattern, transform_filename


def test_apply_pattern():
    assert apply_pattern("My Document", "lower") == "my document"
    assert apply_pattern("My Document", "upper") == "MY DOCUMENT"
    assert apply_pattern("my document", "title") == "My Document"
    assert apply_pattern("my test file", "kebab-spaces") == "my-test-file"
    assert apply_pattern("my test file", "snake-spaces") == "my_test_file"
    assert apply_pattern("doc123_45.txt", "remove-numbers") == "doc_.txt"
    assert apply_pattern("hello #world! (test)", "remove-special") == "helloworldtest"


def test_apply_pattern_invalid():
    with pytest.raises(ValueError):
        apply_pattern("name", "unknown-pattern")


def test_transform_filename_prefix_suffix():
    result = transform_filename("file.txt", prefix="pre_", suffix="_post")
    assert result == "pre_file_post.txt"


def test_transform_filename_sequence():
    result = transform_filename("item.png", sequence_num=5, padding=3)
    assert result == "item_005.png"


def test_transform_filename_extensionless():
    result = transform_filename("Dockerfile", pattern="lower", suffix="_v1")
    assert result == "dockerfile_v1"


def test_transform_filename_hidden_file():
    result = transform_filename(".gitignore", suffix="_backup")
    assert result == ".gitignore_backup"
