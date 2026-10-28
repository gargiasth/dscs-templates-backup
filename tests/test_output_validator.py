"""
Tests for validation/output_validator.py

Run from the repo root:
    pytest tests/test_output_validator.py
"""

from pathlib import Path

import pytest

from validation.output_validator import (
    prepare_output, finish_output, staging_path, OutputValidationError, MARKER, STAGING_ROOT,
)


def write(path, text="id\n1\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestPrepareOutput:

    def test_missing_output_folder_is_created(self, tmp_path):
        out = tmp_path / "etl_output"
        prepare_output(out)
        assert out.is_dir()

    def test_returns_an_empty_local_holding_folder(self, tmp_path):
        # held on local disk, not next to the output: volumes stall on long-held file handles
        out = tmp_path / "etl_output"
        staging = prepare_output(out)
        assert staging == staging_path(out) and staging.parent == STAGING_ROOT
        assert list(staging.iterdir()) == []

    def test_two_outputs_get_different_holding_folders(self, tmp_path):
        assert staging_path(tmp_path / "a" / "out") != staging_path(tmp_path / "b" / "out")

    def test_existing_files_are_allowed(self, tmp_path):
        write(tmp_path / "out" / "old.csv")
        prepare_output(tmp_path / "out")          # no error

    def test_leftover_holding_folder_is_cleared(self, tmp_path):
        out = tmp_path / "out"
        write(staging_path(out) / "stale.csv")
        staging = prepare_output(out)
        assert list(staging.iterdir()) == []

    def test_unwritable_folder_names_the_privilege(self, tmp_path, monkeypatch):
        def deny(self, *a, **k):
            raise PermissionError("denied")
        monkeypatch.setattr(Path, "write_text", deny)
        with pytest.raises(OutputValidationError, match="WRITE VOLUME on the volume"):
            prepare_output(tmp_path / "out")

    def test_snowflake_privilege_wording(self, tmp_path, monkeypatch):
        def deny(self, *a, **k):
            raise PermissionError("denied")
        monkeypatch.setattr(Path, "write_text", deny)
        with pytest.raises(OutputValidationError, match="WRITE on the stage"):
            prepare_output(tmp_path / "out", platform="snowflake")


class TestFinishOutput:

    def test_new_files_are_moved_in_and_holding_folder_removed(self, tmp_path):
        out = tmp_path / "out"
        staging = prepare_output(out)
        write(staging / "person.csv")
        write(staging / "control" / "state.txt")
        moved = finish_output(out, staging)
        assert (out / "person.csv").exists() and (out / "control" / "state.txt").exists()
        assert len(moved) == 2 and not staging.exists()

    def test_existing_files_with_other_names_are_kept(self, tmp_path):
        out = tmp_path / "out"
        write(out / "old.csv", "old\n1\n")
        staging = prepare_output(out)
        write(staging / "new.csv")
        finish_output(out, staging)
        assert (out / "old.csv").read_text() == "old\n1\n" and (out / "new.csv").exists()

    def test_same_name_is_refused_and_nothing_is_overwritten(self, tmp_path):
        out = tmp_path / "out"
        write(out / "person.csv", "old\n1\n")
        staging = prepare_output(out)
        write(staging / "person.csv", "new\n2\n")
        write(staging / "death.csv")
        with pytest.raises(OutputValidationError, match="1 new file\\(s\\) have the same name.*person.csv"):
            finish_output(out, staging)
        assert (out / "person.csv").read_text() == "old\n1\n"     # untouched
        assert not (out / "death.csv").exists()                     # nothing moved
        assert (staging / "person.csv").exists()                    # new files kept for inspection

    def test_same_name_in_a_different_subfolder_is_fine(self, tmp_path):
        out = tmp_path / "out"
        write(out / "DE_1" / "a.csv")
        staging = prepare_output(out)
        write(staging / "DE_2" / "a.csv")
        finish_output(out, staging)
        assert (out / "DE_2" / "a.csv").exists()

    def test_many_clashes_are_summarised(self, tmp_path):
        out = tmp_path / "out"
        staging = prepare_output(out)
        for i in range(7):
            write(out / f"f{i}.csv"); write(staging / f"f{i}.csv")
        with pytest.raises(OutputValidationError, match="7 new file.*and 2 more"):
            finish_output(out, staging)

    def test_nothing_written_fails(self, tmp_path):
        out = tmp_path / "out"
        staging = prepare_output(out)
        with pytest.raises(OutputValidationError, match="wrote nothing"):
            finish_output(out, staging)
        assert not staging.exists()

    def test_only_zero_byte_files_fails(self, tmp_path):
        out = tmp_path / "out"
        staging = prepare_output(out)
        write(staging / "_SUCCESS", "")
        with pytest.raises(OutputValidationError, match="wrote nothing"):
            finish_output(out, staging)

    def test_missing_holding_folder_fails(self, tmp_path):
        with pytest.raises(OutputValidationError, match="wrote nothing"):
            finish_output(tmp_path / "out", tmp_path / "gone")