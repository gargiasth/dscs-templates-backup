# test_transform_silver.py
## Unit tests for transforms/silver.py::transform_silver
## Covers: happy, angry, delinquent, desolate, forgetful paths
## Black box + white box + logging assertions

import pytest
import pandas as pd
from unittest.mock import patch

from transforms.silver import transform_silver, NULL_VALUES


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def clean_df():
    """No duplicates, no null placeholders — ideal input."""
    return pd.DataFrame({
        "case_id":      ["C1", "C2", "C3"],
        "disease_type": ["TypeA", "TypeB", "TypeC"],
        "sample_type":  ["Primary Tumor", "Blood Derived Normal", "Metastatic"],
    })

@pytest.fixture
def df_with_duplicates():
    """Two identical rows followed by a unique row."""
    return pd.DataFrame({
        "case_id":  ["C1", "C1", "C2"],
        "disease":  ["TypeA", "TypeA", "TypeB"],
    })

@pytest.fixture
def df_with_null_placeholders():
    """Each known null placeholder string in its own row."""
    return pd.DataFrame({
        "case_id":    [f"C{i}" for i in range(len(NULL_VALUES))],
        "morphology": NULL_VALUES,
    })

@pytest.fixture
def empty_df():
    """Empty DataFrame with columns defined."""
    return pd.DataFrame(columns=["case_id", "disease_type"])


# ── Happy Path ────────────────────────────────────────────────────────────────

def test_transform_silver_happy_path_returns_dataframe(clean_df):
    # Arrange — clean_df fixture
    # Act
    result = transform_silver(clean_df)
    # Assert
    assert isinstance(result, pd.DataFrame)


def test_transform_silver_happy_path_clean_input_preserves_all_rows(clean_df):
    # Arrange
    expected_len = len(clean_df)
    # Act
    result = transform_silver(clean_df)
    # Assert
    assert len(result) == expected_len


def test_transform_silver_happy_path_removes_duplicate_rows(df_with_duplicates):
    # Arrange — 3 rows, 2 identical → expect 2 unique rows
    # Act
    result = transform_silver(df_with_duplicates)
    # Assert
    assert len(result) == 2


def test_transform_silver_happy_path_valid_value_not_modified(df_with_null_placeholders):
    # Arrange — add a row with a real morphology code
    df = pd.concat([df_with_null_placeholders,
                    pd.DataFrame({"case_id": ["C99"], "morphology": ["8500/3"]})],
                   ignore_index=True)
    # Act
    result = transform_silver(df)
    # Assert
    assert result.loc[result["case_id"] == "C99", "morphology"].values[0] == "8500/3"


def test_transform_silver_happy_path_all_null_placeholders_replaced(df_with_null_placeholders):
    # Arrange — every morphology value is a known placeholder
    # Act
    result = transform_silver(df_with_null_placeholders)
    # Assert
    assert result["morphology"].isna().all()


# ── White Box ─────────────────────────────────────────────────────────────────

def test_transform_silver_whitebox_index_reset_after_dedup(df_with_duplicates):
    # White box: reset_index(drop=True) produces 0-based sequential index
    result = transform_silver(df_with_duplicates)
    assert list(result.index) == list(range(len(result)))


def test_transform_silver_whitebox_keep_first_duplicate_survives():
    # White box: drop_duplicates(keep="first") — original order is preserved
    # Row 0 (C1/TypeA) is kept; row 1 (identical) is dropped; row 2 (C2) kept
    df = pd.DataFrame({
        "case_id": ["C1", "C1", "C2"],
        "disease": ["TypeA", "TypeA", "TypeB"],
    })
    result = transform_silver(df)
    assert result.iloc[0]["case_id"] == "C1"
    assert result.iloc[1]["case_id"] == "C2"


def test_transform_silver_whitebox_replacement_is_pd_na_sentinel():
    # White box: replace uses pd.NA — not None, not np.nan
    df = pd.DataFrame({"col": ["Not Reported"]})
    result = transform_silver(df)
    assert pd.isna(result.loc[0, "col"])


def test_transform_silver_whitebox_case_sensitive_not_reported_uppercase_only():
    # White box: "NOT REPORTED" (all caps) is not in NULL_VALUES — not replaced
    df = pd.DataFrame({"col": ["NOT REPORTED"]})
    result = transform_silver(df)
    assert result.loc[0, "col"] == "NOT REPORTED"


def test_transform_silver_whitebox_dedup_runs_before_replace():
    # White box: two identical "Unknown" rows → dedup first leaves one row, then replace
    df = pd.DataFrame({
        "case_id":    ["C1", "C1"],
        "morphology": ["Unknown", "Unknown"],
    })
    result = transform_silver(df)
    assert len(result) == 1
    assert pd.isna(result.loc[0, "morphology"])


def test_transform_silver_whitebox_each_null_value_string_replaced():
    # White box: every entry in NULL_VALUES is individually replaced
    for placeholder in NULL_VALUES:
        df = pd.DataFrame({"col": [placeholder]})
        result = transform_silver(df)
        assert pd.isna(result.loc[0, "col"]), f"Expected pd.NA for placeholder: '{placeholder}'"


# ── Desolate Path ─────────────────────────────────────────────────────────────

def test_transform_silver_desolate_empty_df_returns_empty(empty_df):
    # Arrange — empty DataFrame
    # Act
    result = transform_silver(empty_df)
    # Assert — empty is valid; should not raise
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 0


def test_transform_silver_desolate_empty_df_preserves_columns(empty_df):
    # Arrange
    expected_cols = list(empty_df.columns)
    # Act
    result = transform_silver(empty_df)
    # Assert
    assert list(result.columns) == expected_cols


def test_transform_silver_desolate_all_identical_rows_returns_one_row():
    # Arrange — 100 identical rows
    df = pd.DataFrame({
        "case_id": ["C1"] * 100,
        "disease": ["TypeA"] * 100,
    })
    # Act
    result = transform_silver(df)
    # Assert
    assert len(result) == 1


def test_transform_silver_desolate_existing_nan_not_affected():
    # Arrange — column already contains NaN (not a placeholder string)
    df = pd.DataFrame({"col": [float("nan"), "real_value"]})
    # Act
    result = transform_silver(df)
    # Assert — NaN remains NaN; "real_value" unchanged
    assert pd.isna(result.loc[0, "col"])
    assert result.loc[1, "col"] == "real_value"


# ── Angry Path ────────────────────────────────────────────────────────────────

def test_transform_silver_angry_path_raises_on_none_input():
    # Arrange
    # Act / Assert
    with pytest.raises((AttributeError, TypeError)):
        transform_silver(None)


def test_transform_silver_angry_path_raises_on_list_input():
    # Arrange
    # Act / Assert
    with pytest.raises(AttributeError):
        transform_silver([{"case_id": "C1", "disease": "TypeA"}])


def test_transform_silver_angry_path_raises_on_dict_input():
    # Arrange
    # Act / Assert
    with pytest.raises(AttributeError):
        transform_silver({"case_id": ["C1"], "disease": ["TypeA"]})


def test_transform_silver_angry_path_raises_on_string_input():
    # Arrange
    # Act / Assert
    with pytest.raises((AttributeError, TypeError)):
        transform_silver("not a dataframe")


# ── Delinquent Path ───────────────────────────────────────────────────────────

def test_transform_silver_delinquent_sql_injection_string_passed_through():
    # Arrange — SQL injection payload should not be treated as a null placeholder
    df = pd.DataFrame({"col": ["'; DROP TABLE cases; --"]})
    # Act
    result = transform_silver(df)
    # Assert
    assert result.loc[0, "col"] == "'; DROP TABLE cases; --"


def test_transform_silver_delinquent_unicode_values_passed_through():
    # Arrange — unicode / emoji values are not placeholders
    df = pd.DataFrame({"col": ["日本語", "αβγ", "👾"]})
    # Act
    result = transform_silver(df)
    # Assert
    assert list(result["col"]) == ["日本語", "αβγ", "👾"]


def test_transform_silver_delinquent_whitespace_variant_not_replaced():
    # Arrange — leading space makes it not match any known placeholder
    df = pd.DataFrame({"col": [" Not Reported", "Not Reported "]})
    # Act
    result = transform_silver(df)
    # Assert
    assert result.loc[0, "col"] == " Not Reported"
    assert result.loc[1, "col"] == "Not Reported "


def test_transform_silver_delinquent_mixed_types_placeholder_among_ints():
    # Arrange — object column mixing int and placeholder string
    df = pd.DataFrame({"col": ["Not Reported", 42, 3.14]})
    # Act
    result = transform_silver(df)
    # Assert — only the placeholder is replaced
    assert pd.isna(result.loc[0, "col"])
    assert result.loc[1, "col"] == 42


# ── Forgetful Path ────────────────────────────────────────────────────────────

def test_transform_silver_forgetful_large_dataframe_completes():
    # Arrange — 100k rows, half placeholders
    df = pd.DataFrame({
        "case_id":    [f"C{i}" for i in range(100_000)],
        "morphology": ["Not Reported"] * 50_000 + ["8500/3"] * 50_000,
    })
    # Act
    result = transform_silver(df)
    # Assert — all rows present (no duplicates since case_id is unique)
    assert len(result) == 100_000


def test_transform_silver_forgetful_wide_dataframe_completes():
    # Arrange — 10 rows, 500 columns all containing placeholders
    df = pd.DataFrame({f"col_{i}": ["Not Reported"] * 10 for i in range(500)})
    # Act
    result = transform_silver(df)
    # Assert — all values replaced, no raise
    assert result.isna().all().all()


# ── Logging Assertions ────────────────────────────────────────────────────────

def test_transform_silver_logging_info_called_once_on_success(clean_df):
    # Arrange
    with patch("transforms.silver.logger") as mock_logger:
        # Act
        transform_silver(clean_df)
        # Assert
        mock_logger.info.assert_called_once()


def test_transform_silver_logging_info_message_contains_row_count(clean_df):
    # Arrange
    with patch("transforms.silver.logger") as mock_logger:
        # Act
        transform_silver(clean_df)
        # Assert
        message = mock_logger.info.call_args[0][0]
        assert str(len(clean_df)) in message


def test_transform_silver_logging_info_message_contains_dupes_dropped_count(df_with_duplicates):
    # Arrange — 1 duplicate will be dropped
    with patch("transforms.silver.logger") as mock_logger:
        # Act
        transform_silver(df_with_duplicates)
        # Assert
        message = mock_logger.info.call_args[0][0]
        assert "1" in message


def test_transform_silver_logging_info_zero_dupes_when_no_duplicates(clean_df):
    # Arrange
    with patch("transforms.silver.logger") as mock_logger:
        # Act
        transform_silver(clean_df)
        # Assert — message should note 0 duplicates dropped
        message = mock_logger.info.call_args[0][0]
        assert "0" in message


def test_transform_silver_logging_error_not_called_on_success(clean_df):
    # Arrange
    with patch("transforms.silver.logger") as mock_logger:
        # Act
        transform_silver(clean_df)
        # Assert
        mock_logger.error.assert_not_called()
