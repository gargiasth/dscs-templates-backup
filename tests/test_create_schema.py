# test_create_schema.py
## Unit tests for spcs/schema_setup.py::create_schema
##
## Requirements under test:
##   R1. Schema does not exist → create it, log "Schema {db}.{schema} created successfully"
##   R2. Schema already exists → skip creation, log "Schema {db}.{schema} already exists — skipping creation"
##   R3. Any error          → log the error and re-raise the exception
##
## NOTE: os.environ defaults are set BEFORE any project imports.
## config.database reads ACTIVE_DATABASE at import time; if it sees "snowflake"
## it attempts a live Snowflake connection. Setting it to "duckdb" here
## prevents that without requiring a real database.

import os
os.environ.setdefault("ACTIVE_DATABASE",    "duckdb")
os.environ.setdefault("SNOWFLAKE_DATABASE", "test_db")
os.environ.setdefault("SNOWFLAKE_SCHEMA",   "test_schema")

import pytest
from unittest.mock import patch, MagicMock, call

from spcs.schema_setup import create_schema


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def snowflake_env(monkeypatch):
    """Provides standard, valid Snowflake env vars for tests that need them."""
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "my_database")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA",   "my_schema")


@pytest.fixture
def mock_conn():
    """Bare MagicMock connection; configure fetchone per test to control branch."""
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None  # default: schema does not exist
    return conn


@pytest.fixture
def mock_engine(mock_conn):
    """MagicMock engine whose connect() context manager yields mock_conn."""
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = mock_conn
    engine.connect.return_value.__exit__.return_value = False
    return engine


# ── Helper: configure whether schema "exists" on the mock connection ──────────

def _schema_does_not_exist(mock_conn):
    """Simulate the database reporting the schema is absent."""
    mock_conn.execute.return_value.fetchone.return_value = None


def _schema_already_exists(mock_conn):
    """Simulate the database reporting the schema is present."""
    mock_conn.execute.return_value.fetchone.return_value = ("my_schema",)


# ── Happy Path — schema does not exist (R1) ───────────────────────────────────

def test_create_schema_happy_path_returns_none_when_schema_created(snowflake_env, mock_engine, mock_conn):
    # Arrange
    _schema_does_not_exist(mock_conn)
    # Act
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        result = create_schema()
    # Assert — void function must return None
    assert result is None


def test_create_schema_happy_path_does_not_raise_when_schema_created(snowflake_env, mock_engine, mock_conn):
    # Arrange
    _schema_does_not_exist(mock_conn)
    # Act / Assert
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        create_schema()  # must not raise


def test_create_schema_happy_path_logs_created_successfully(snowflake_env, mock_engine, mock_conn):
    # Arrange
    _schema_does_not_exist(mock_conn)
    # Act
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            create_schema()
    # Assert — R1 requires "created successfully" in the log message
    message = mock_logger.info.call_args[0][0]
    assert "created successfully" in message


def test_create_schema_happy_path_created_log_contains_database_and_schema(monkeypatch, mock_engine, mock_conn):
    # Arrange
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "prod_db")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA",   "prod_schema")
    _schema_does_not_exist(mock_conn)
    # Act
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            create_schema()
    # Assert
    message = mock_logger.info.call_args[0][0]
    assert "prod_db" in message
    assert "prod_schema" in message


# ── Happy Path — schema already exists (R2) ───────────────────────────────────

def test_create_schema_happy_path_does_not_raise_when_schema_exists(snowflake_env, mock_engine, mock_conn):
    # Arrange
    _schema_already_exists(mock_conn)
    # Act / Assert
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        create_schema()  # must not raise


def test_create_schema_happy_path_returns_none_when_schema_exists(snowflake_env, mock_engine, mock_conn):
    # Arrange
    _schema_already_exists(mock_conn)
    # Act
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        result = create_schema()
    # Assert
    assert result is None


def test_create_schema_happy_path_logs_already_exists_when_schema_present(snowflake_env, mock_engine, mock_conn):
    # Arrange
    _schema_already_exists(mock_conn)
    # Act
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            create_schema()
    # Assert — R2 requires "already exists" in the log message
    message = mock_logger.info.call_args[0][0]
    assert "already exists" in message


def test_create_schema_happy_path_skipping_log_contains_database_and_schema(monkeypatch, mock_engine, mock_conn):
    # Arrange
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "prod_db")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA",   "prod_schema")
    _schema_already_exists(mock_conn)
    # Act
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            create_schema()
    # Assert
    message = mock_logger.info.call_args[0][0]
    assert "prod_db" in message
    assert "prod_schema" in message


def test_create_schema_happy_path_skipping_log_contains_skipping_creation(snowflake_env, mock_engine, mock_conn):
    # Arrange
    _schema_already_exists(mock_conn)
    # Act
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            create_schema()
    # Assert — R2 exact phrase
    message = mock_logger.info.call_args[0][0]
    assert "skipping" in message.lower()


# ── Black Box — branch isolation ──────────────────────────────────────────────

def test_create_schema_blackbox_created_log_not_emitted_when_schema_exists(snowflake_env, mock_engine, mock_conn):
    # Black box: R1 log must NOT appear when R2 path is taken
    _schema_already_exists(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            create_schema()
    message = mock_logger.info.call_args[0][0]
    assert "created successfully" not in message


def test_create_schema_blackbox_skipping_log_not_emitted_when_schema_created(snowflake_env, mock_engine, mock_conn):
    # Black box: R2 log must NOT appear when R1 path is taken
    _schema_does_not_exist(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            create_schema()
    message = mock_logger.info.call_args[0][0]
    assert "already exists" not in message


def test_create_schema_blackbox_exactly_one_info_log_on_create(snowflake_env, mock_engine, mock_conn):
    # Black box: exactly one info-level log on success — not zero, not two
    _schema_does_not_exist(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            create_schema()
    assert mock_logger.info.call_count == 1


def test_create_schema_blackbox_exactly_one_info_log_when_schema_exists(snowflake_env, mock_engine, mock_conn):
    # Black box: exactly one info-level log on skip — not zero, not two
    _schema_already_exists(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            create_schema()
    assert mock_logger.info.call_count == 1


# ── White Box — internal branch behavior ─────────────────────────────────────

def test_create_schema_whitebox_create_sql_issued_when_schema_not_found(snowflake_env, mock_engine, mock_conn):
    # White box: when schema doesn't exist, a CREATE statement must be executed
    _schema_does_not_exist(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        create_schema()
    executed_sqls = [str(c[0][0]) for c in mock_conn.execute.call_args_list]
    assert any("CREATE" in sql.upper() for sql in executed_sqls)


def test_create_schema_whitebox_create_sql_not_issued_when_schema_exists(snowflake_env, mock_engine, mock_conn):
    # White box: when schema already exists, no CREATE statement must be executed
    _schema_already_exists(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        create_schema()
    executed_sqls = [str(c[0][0]) for c in mock_conn.execute.call_args_list]
    assert not any("CREATE SCHEMA" in sql.upper() for sql in executed_sqls)


def test_create_schema_whitebox_database_appears_in_create_sql(monkeypatch, mock_engine, mock_conn):
    # White box: CREATE statement targets the correct database identifier
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "target_db")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA",   "target_schema")
    _schema_does_not_exist(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        create_schema()
    executed_sqls = [str(c[0][0]) for c in mock_conn.execute.call_args_list]
    create_sql = next(sql for sql in executed_sqls if "CREATE" in sql.upper())
    assert "target_db" in create_sql


def test_create_schema_whitebox_schema_appears_in_create_sql(monkeypatch, mock_engine, mock_conn):
    # White box: CREATE statement targets the correct schema identifier
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "target_db")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA",   "target_schema")
    _schema_does_not_exist(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        create_schema()
    executed_sqls = [str(c[0][0]) for c in mock_conn.execute.call_args_list]
    create_sql = next(sql for sql in executed_sqls if "CREATE" in sql.upper())
    assert "target_schema" in create_sql


def test_create_schema_whitebox_engine_connect_is_used_as_context_manager(snowflake_env, mock_engine, mock_conn):
    # White box: connection must be opened and closed via context manager
    _schema_does_not_exist(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        create_schema()
    mock_engine.connect.return_value.__enter__.assert_called_once()
    mock_engine.connect.return_value.__exit__.assert_called_once()


# ── Desolate Path ─────────────────────────────────────────────────────────────

def test_create_schema_desolate_missing_database_env_still_executes(monkeypatch, mock_engine, mock_conn):
    # Desolate: SNOWFLAKE_DATABASE not set — no guard in function, uses None as identifier
    monkeypatch.delenv("SNOWFLAKE_DATABASE", raising=False)
    monkeypatch.setenv("SNOWFLAKE_SCHEMA", "some_schema")
    _schema_does_not_exist(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        create_schema()  # must not raise from missing env var alone
    mock_conn.execute.assert_called()


def test_create_schema_desolate_missing_schema_env_still_executes(monkeypatch, mock_engine, mock_conn):
    # Desolate: SNOWFLAKE_SCHEMA not set — no guard in function, uses None as identifier
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "some_db")
    monkeypatch.delenv("SNOWFLAKE_SCHEMA", raising=False)
    _schema_does_not_exist(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        create_schema()  # must not raise from missing env var alone
    mock_conn.execute.assert_called()


def test_create_schema_desolate_both_env_vars_missing_still_executes(monkeypatch, mock_engine, mock_conn):
    # Desolate: both env vars absent — function has no validation guard
    monkeypatch.delenv("SNOWFLAKE_DATABASE", raising=False)
    monkeypatch.delenv("SNOWFLAKE_SCHEMA",   raising=False)
    _schema_does_not_exist(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        create_schema()
    mock_conn.execute.assert_called()


# ── Angry Path (R3) ───────────────────────────────────────────────────────────

def test_create_schema_angry_path_raises_when_connect_fails(snowflake_env, mock_engine):
    # Angry: engine.connect() raises — R3 requires re-raise
    mock_engine.connect.return_value.__enter__.side_effect = Exception("Connection refused")
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with pytest.raises(Exception, match="Connection refused"):
            create_schema()


def test_create_schema_angry_path_raises_when_execute_fails(snowflake_env, mock_engine, mock_conn):
    # Angry: conn.execute() raises — R3 requires re-raise
    mock_conn.execute.side_effect = Exception("SQL execution failed")
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with pytest.raises(Exception, match="SQL execution failed"):
            create_schema()


def test_create_schema_angry_path_original_exception_type_preserved(snowflake_env, mock_engine, mock_conn):
    # Angry: re-raise must not wrap the exception — R3 says re-raise the exception
    mock_conn.execute.side_effect = PermissionError("Insufficient privileges")
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with pytest.raises(PermissionError):
            create_schema()


def test_create_schema_angry_path_logs_error_on_connection_failure(snowflake_env, mock_engine):
    # Angry: R3 requires logging the error before re-raising
    mock_engine.connect.return_value.__enter__.side_effect = Exception("DB unavailable")
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            with pytest.raises(Exception):
                create_schema()
    mock_logger.error.assert_called_once()


def test_create_schema_angry_path_logs_error_on_execute_failure(snowflake_env, mock_engine, mock_conn):
    # Angry: R3 requires logging the error before re-raising
    mock_conn.execute.side_effect = Exception("Execute failed")
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            with pytest.raises(Exception):
                create_schema()
    mock_logger.error.assert_called_once()


def test_create_schema_angry_path_error_log_contains_schema_path(monkeypatch, mock_engine, mock_conn):
    # Angry: error message should identify which schema failed
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "my_database")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA",   "my_schema")
    mock_conn.execute.side_effect = Exception("DB error")
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            with pytest.raises(Exception):
                create_schema()
    message = mock_logger.error.call_args[0][0]
    assert "my_database" in message
    assert "my_schema" in message


# ── Delinquent Path ───────────────────────────────────────────────────────────

def test_create_schema_delinquent_injection_in_database_env_reaches_sql(monkeypatch, mock_engine, mock_conn):
    # Delinquent: SQL injection via env var is interpolated without sanitization
    # This test documents a known vulnerability (no parameterization)
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "db; DROP SCHEMA real_schema; --")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA",   "sc")
    _schema_does_not_exist(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        create_schema()
    executed_sqls = [str(c[0][0]) for c in mock_conn.execute.call_args_list]
    assert any("DROP SCHEMA" in sql for sql in executed_sqls)


def test_create_schema_delinquent_injection_in_schema_env_reaches_sql(monkeypatch, mock_engine, mock_conn):
    # Delinquent: SQL injection via SNOWFLAKE_SCHEMA also reaches SQL unescaped
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "db")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA",   "sc; DROP TABLE cases; --")
    _schema_does_not_exist(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        create_schema()
    executed_sqls = [str(c[0][0]) for c in mock_conn.execute.call_args_list]
    assert any("DROP TABLE" in sql for sql in executed_sqls)


def test_create_schema_delinquent_special_chars_in_name_not_sanitized(monkeypatch, mock_engine, mock_conn):
    # Delinquent: special characters in env vars pass through to SQL unmodified
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "db-name_v2")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA",   "schema.v2")
    _schema_does_not_exist(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        create_schema()
    executed_sqls = [str(c[0][0]) for c in mock_conn.execute.call_args_list]
    assert any("db-name_v2" in sql for sql in executed_sqls)


# ── Forgetful Path ────────────────────────────────────────────────────────────

def test_create_schema_forgetful_timeout_on_connect_propagates(snowflake_env, mock_engine):
    # Forgetful: connection timeout must propagate — R3
    mock_engine.connect.return_value.__enter__.side_effect = TimeoutError("Connection timed out")
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with pytest.raises(TimeoutError):
            create_schema()


def test_create_schema_forgetful_network_error_on_execute_propagates(snowflake_env, mock_engine, mock_conn):
    # Forgetful: mid-query network drop must propagate — R3
    mock_conn.execute.side_effect = ConnectionError("Network interrupted")
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with pytest.raises(ConnectionError):
            create_schema()


def test_create_schema_forgetful_os_error_on_connect_propagates(snowflake_env, mock_engine):
    # Forgetful: OS-level socket failure must propagate — R3
    mock_engine.connect.return_value.__enter__.side_effect = OSError("Socket error")
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with pytest.raises(OSError):
            create_schema()


# ── Logging Guard ─────────────────────────────────────────────────────────────

def test_create_schema_logging_error_not_called_on_successful_create(snowflake_env, mock_engine, mock_conn):
    # Logging: logger.error must not fire on a successful create
    _schema_does_not_exist(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            create_schema()
    mock_logger.error.assert_not_called()


def test_create_schema_logging_error_not_called_when_schema_already_exists(snowflake_env, mock_engine, mock_conn):
    # Logging: logger.error must not fire on a successful skip
    _schema_already_exists(mock_conn)
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            create_schema()
    mock_logger.error.assert_not_called()


def test_create_schema_logging_info_not_called_when_error_raised(snowflake_env, mock_engine, mock_conn):
    # Logging: logger.info must not fire if an exception interrupts execution
    mock_conn.execute.side_effect = Exception("DB error")
    with patch("spcs.schema_setup.ACTIVE_ENGINE", mock_engine):
        with patch("spcs.schema_setup.logger") as mock_logger:
            with pytest.raises(Exception):
                create_schema()
    mock_logger.info.assert_not_called()
