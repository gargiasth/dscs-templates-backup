# test_helpers.py
## Unit tests for utils/helpers.py
### Covers: Happy Path, Angry Path, Desolate Path, Delinquent Path, Forgetful Path

import os
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from utils.helpers import write_df_to_table



# Happy Path
def test_write_df_to_table_calls_to_sql():
    """Calls df.to_sql with correct arguments"""
    df     = pd.DataFrame({"case_id": ["abc"], "disease_type": ["Cancer"]})
    engine = MagicMock()
    with patch.object(df, "to_sql") as mock_to_sql:
        write_df_to_table(df, "bronze_cases", engine)
        mock_to_sql.assert_called_once_with("bronze_cases", engine, if_exists="append", index=False)


def test_write_df_to_table_default_append_mode():
    """Defaults to append mode"""
    df     = pd.DataFrame({"case_id": ["abc"]})
    engine = MagicMock()
    with patch.object(df, "to_sql") as mock_to_sql:
        write_df_to_table(df, "bronze_cases", engine)
        _, kwargs = mock_to_sql.call_args
        assert kwargs["if_exists"] == "append"


def test_write_df_to_table_replace_mode():
    """Accepts replace mode"""
    df     = pd.DataFrame({"case_id": ["abc"]})
    engine = MagicMock()
    with patch.object(df, "to_sql") as mock_to_sql:
        write_df_to_table(df, "bronze_cases", engine, if_exists="replace")
        _, kwargs = mock_to_sql.call_args
        assert kwargs["if_exists"] == "replace"


# Angry Path
def test_write_df_to_table_raises_on_db_failure():
    """Raises and logs on database connection failure"""
    df     = pd.DataFrame({"case_id": ["abc"]})
    engine = MagicMock()
    with patch.object(df, "to_sql", side_effect=Exception("DB connection lost")):
        with pytest.raises(Exception, match="DB connection lost"):
            write_df_to_table(df, "bronze_cases", engine)


# Desolate Path
def test_write_df_to_table_empty_dataframe():
    """Handles empty DataFrame without error"""
    df     = pd.DataFrame()
    engine = MagicMock()
    with patch.object(df, "to_sql") as mock_to_sql:
        write_df_to_table(df, "bronze_cases", engine)
        mock_to_sql.assert_called_once()


def test_write_df_to_table_empty_table_name():
    """Raises when table name is empty string"""
    df     = pd.DataFrame({"case_id": ["abc"]})
    engine = MagicMock()
    with pytest.raises(Exception):
        write_df_to_table(df, "", engine)


# Delinquent Path
def test_write_df_to_table_sql_injection_in_table_name():
    """Handles SQL injection attempt in table name"""
    df     = pd.DataFrame({"case_id": ["abc"]})
    engine = MagicMock()
    with patch.object(df, "to_sql", side_effect=Exception("Invalid table name")):
        with pytest.raises(Exception):
            write_df_to_table(df, "bronze_cases; DROP TABLE bronze_cases", engine)


def test_write_df_to_table_invalid_if_exists():
    """Raises when invalid if_exists value is passed"""
    df     = pd.DataFrame({"case_id": ["abc"]})
    engine = MagicMock()
    with patch.object(df, "to_sql", side_effect=ValueError("Invalid if_exists")):
        with pytest.raises(ValueError):
            write_df_to_table(df, "bronze_cases", engine, if_exists="invalid")


# Forgetful Path
def test_write_df_to_table_raises_on_timeout():
    """Raises when database connection times out"""
    df     = pd.DataFrame({"case_id": ["abc"]})
    engine = MagicMock()
    with patch.object(df, "to_sql", side_effect=TimeoutError("Connection timed out")):
        with pytest.raises(TimeoutError):
            write_df_to_table(df, "bronze_cases", engine)


def test_write_df_to_table_raises_on_network_disconnect():
    """Raises when network disconnects mid-write"""
    df     = pd.DataFrame({"case_id": ["abc"]})
    engine = MagicMock()
    with patch.object(df, "to_sql", side_effect=ConnectionError("Network disconnected")):
        with pytest.raises(ConnectionError):
            write_df_to_table(df, "bronze_cases", engine)