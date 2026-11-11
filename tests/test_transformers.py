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


def test_hidden_name_keeps_a_real_extension():
    # Names that only look extensionless because they start with a dot used to
    # absorb the suffix into the stem: ".env.local" + "_bak" became
    # ".env.local_bak", and uppercasing rewrote ".Local".
    assert transform_filename(".env", suffix="_backup") == ".env_backup"
    assert transform_filename(".env.local", suffix="_bak") == ".env_bak.local"
    assert transform_filename(".Env.Local", pattern="upper") == ".ENV.Local"
    assert transform_filename(".Env.Local", pattern="lower") == ".env.Local"
    assert transform_filename("..secret.txt", suffix="_bak") == "..secret_bak.txt"
    # The digit sits in the stem, so the ".env" suffix is unchanged.
    assert transform_filename(".v2.env", pattern="remove-numbers") == ".v.env"


def test_trailing_dot_split_stays_compatible():
    assert transform_filename("foo.", suffix="_x") == "foo_x."
    assert transform_filename("a.b.", pattern="upper") == "A.B."
    assert transform_filename("My File.TAR.GZ", pattern="lower", suffix="_v2") == "my file.tar_v2.GZ"
    assert transform_filename("file name.txt", pattern="upper") == "FILE NAME.txt"


def test_replace_is_literal_and_runs_before_other_transforms():
    assert transform_filename("a.txt", replacements=[(".", "_")]) == "a_txt"
    assert transform_filename("Photo.txt", replacements=[("photo", "pic")]) == "Photo.txt"
    assert transform_filename("ab.txt", replacements=[("a", "")]) == "b.txt"
    assert transform_filename("ab.txt", replacements=[("a", "b"), ("b", "c")]) == "cc.txt"
    assert (
        transform_filename(
            "IMG_1.JPEG",
            replacements=[("IMG_", "vacation_"), (".JPEG", ".jpg")],
            pattern="lower",
            prefix="pre_",
        )
        == "pre_vacation_1.jpg"
    )
    assert transform_filename("My File.JPEG", replacements=[(".JPEG", ".jpg")], pattern="lower") == (
        "my file.jpg"
    )


def test_empty_or_non_string_replacement_is_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        transform_filename("a.txt", replacements=[("", "x")])
    with pytest.raises(ValueError, match="pair of strings"):
        transform_filename("a.txt", replacements=[(1, "x")])
