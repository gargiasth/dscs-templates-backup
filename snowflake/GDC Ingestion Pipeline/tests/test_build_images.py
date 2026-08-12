# test_build_images.py
## Unit tests for docker/deploy.py::build_images
##
## Requirements under test:
##   R1. Builds all Docker images defined in docker-compose.yml
##   R2. On success  → logs the build output
##   R3. On failure  → logs the error and re-raises the exception
##   R4. Non-zero exit code (check=True) → raises CalledProcessError

import pytest
from subprocess import CalledProcessError
from unittest.mock import patch, MagicMock

from docker.deploy import build_images


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def successful_result():
    """Simulates a completed subprocess.run result with build output."""
    result = MagicMock()
    result.stdout = "Successfully built abc123\nSuccessfully tagged pipeline:latest\n"
    result.returncode = 0
    return result


@pytest.fixture
def empty_result():
    """Simulates a completed subprocess.run result with no stdout output."""
    result = MagicMock()
    result.stdout = ""
    result.returncode = 0
    return result


@pytest.fixture
def mock_subprocess(successful_result):
    """Patches subprocess.run in docker.deploy to return a successful result."""
    with patch("docker.deploy.subprocess.run", return_value=successful_result) as mock_run:
        yield mock_run


# ── Happy Path ────────────────────────────────────────────────────────────────

def test_build_images_happy_path_returns_none(mock_subprocess):
    # Arrange — mock_subprocess returns a successful result by default
    # Act
    result = build_images()
    # Assert — void function must return None
    assert result is None


def test_build_images_happy_path_does_not_raise(mock_subprocess):
    # Arrange — successful subprocess result
    # Act / Assert
    build_images()  # must not raise


def test_build_images_happy_path_calls_subprocess_once(mock_subprocess):
    # Arrange
    # Act
    build_images()
    # Assert — R1: exactly one build command is issued
    mock_subprocess.assert_called_once()


def test_build_images_happy_path_logs_build_output(successful_result):
    # Arrange — R2: on success, build stdout must be logged
    with patch("docker.deploy.subprocess.run", return_value=successful_result):
        with patch("docker.deploy.logger") as mock_logger:
            # Act
            build_images()
    # Assert
    mock_logger.info.assert_called_once_with(successful_result.stdout)


def test_build_images_happy_path_info_log_contains_stdout_content(successful_result):
    # Arrange — R2: logged content must be the actual subprocess output
    with patch("docker.deploy.subprocess.run", return_value=successful_result):
        with patch("docker.deploy.logger") as mock_logger:
            # Act
            build_images()
    # Assert
    logged_message = mock_logger.info.call_args[0][0]
    assert "Successfully built" in logged_message


# ── Black Box ─────────────────────────────────────────────────────────────────

def test_build_images_blackbox_accepts_no_arguments():
    # Black box: function signature takes no parameters
    with patch("docker.deploy.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="")
        build_images()  # must not raise TypeError for missing args


def test_build_images_blackbox_does_not_swallow_subprocess_exception():
    # Black box: any exception from subprocess must propagate to the caller — R3
    with patch("docker.deploy.subprocess.run", side_effect=RuntimeError("Build crashed")):
        with pytest.raises(RuntimeError):
            build_images()


def test_build_images_blackbox_returns_none_not_subprocess_result(successful_result):
    # Black box: caller must receive None, not the raw subprocess result
    with patch("docker.deploy.subprocess.run", return_value=successful_result):
        result = build_images()
    assert result is None


# ── White Box ─────────────────────────────────────────────────────────────────

def test_build_images_whitebox_subprocess_called_with_docker_compose_build(mock_subprocess):
    # White box: R1 implementation must invoke docker-compose build
    build_images()
    args = mock_subprocess.call_args[0][0]
    assert args == ["docker-compose", "build"]


def test_build_images_whitebox_subprocess_called_with_check_true(mock_subprocess):
    # White box: R4 requires check=True so non-zero exit codes raise CalledProcessError
    build_images()
    kwargs = mock_subprocess.call_args[1]
    assert kwargs.get("check") is True


def test_build_images_whitebox_subprocess_called_with_capture_output_true(mock_subprocess):
    # White box: stdout must be captured to be logged — R2
    build_images()
    kwargs = mock_subprocess.call_args[1]
    assert kwargs.get("capture_output") is True


def test_build_images_whitebox_subprocess_called_with_text_true(mock_subprocess):
    # White box: text=True decodes bytes to str so logger.info receives a string
    build_images()
    kwargs = mock_subprocess.call_args[1]
    assert kwargs.get("text") is True


def test_build_images_whitebox_subprocess_called_with_docker_dir_as_cwd(mock_subprocess):
    # White box: cwd must point to the directory containing docker-compose.yml
    from docker.deploy import DOCKER_DIR
    build_images()
    kwargs = mock_subprocess.call_args[1]
    assert kwargs.get("cwd") == DOCKER_DIR


def test_build_images_whitebox_logger_info_called_with_result_stdout(empty_result):
    # White box: logger.info receives result.stdout directly (not a formatted string)
    with patch("docker.deploy.subprocess.run", return_value=empty_result):
        with patch("docker.deploy.logger") as mock_logger:
            build_images()
    mock_logger.info.assert_called_once_with(empty_result.stdout)


# ── Desolate Path ─────────────────────────────────────────────────────────────

def test_build_images_desolate_empty_stdout_does_not_raise(empty_result):
    # Desolate: subprocess succeeds but produces no output — must not raise
    with patch("docker.deploy.subprocess.run", return_value=empty_result):
        build_images()  # must not raise


def test_build_images_desolate_empty_stdout_still_calls_logger_info(empty_result):
    # Desolate: R2 applies even when stdout is empty — info must still be called
    with patch("docker.deploy.subprocess.run", return_value=empty_result):
        with patch("docker.deploy.logger") as mock_logger:
            build_images()
    mock_logger.info.assert_called_once()


def test_build_images_desolate_empty_stdout_logs_empty_string(empty_result):
    # Desolate: empty stdout is logged as-is without substitution
    with patch("docker.deploy.subprocess.run", return_value=empty_result):
        with patch("docker.deploy.logger") as mock_logger:
            build_images()
    logged_message = mock_logger.info.call_args[0][0]
    assert logged_message == ""


def test_build_images_desolate_whitespace_only_stdout_logged_as_is():
    # Desolate: whitespace-only stdout is a valid (if unusual) build output
    result = MagicMock()
    result.stdout = "   \n   "
    with patch("docker.deploy.subprocess.run", return_value=result):
        with patch("docker.deploy.logger") as mock_logger:
            build_images()
    logged_message = mock_logger.info.call_args[0][0]
    assert logged_message == "   \n   "


# ── Angry Path ────────────────────────────────────────────────────────────────

def test_build_images_angry_path_raises_called_process_error_on_nonzero_exit():
    # Angry: R4 — non-zero exit code raises CalledProcessError; must propagate
    with patch("docker.deploy.subprocess.run",
               side_effect=CalledProcessError(returncode=1, cmd=["docker-compose", "build"])):
        with pytest.raises(CalledProcessError):
            build_images()


def test_build_images_angry_path_called_process_error_exit_code_preserved():
    # Angry: R4 — CalledProcessError must carry the original returncode
    with patch("docker.deploy.subprocess.run",
               side_effect=CalledProcessError(returncode=2, cmd=["docker-compose", "build"])):
        with pytest.raises(CalledProcessError) as exc_info:
            build_images()
    assert exc_info.value.returncode == 2


def test_build_images_angry_path_raises_on_file_not_found():
    # Angry: docker-compose not installed — FileNotFoundError must propagate
    with patch("docker.deploy.subprocess.run", side_effect=FileNotFoundError("docker-compose not found")):
        with pytest.raises(FileNotFoundError):
            build_images()


def test_build_images_angry_path_raises_on_permission_error():
    # Angry: insufficient permissions to run docker — PermissionError must propagate
    with patch("docker.deploy.subprocess.run", side_effect=PermissionError("Permission denied")):
        with pytest.raises(PermissionError):
            build_images()


def test_build_images_angry_path_original_exception_type_not_wrapped():
    # Angry: R3 — re-raise must not wrap the original exception in a new type
    with patch("docker.deploy.subprocess.run", side_effect=ValueError("Unexpected error")):
        with pytest.raises(ValueError):
            build_images()


def test_build_images_angry_path_logs_error_on_called_process_error():
    # Angry: R3 — error must be logged before re-raising
    with patch("docker.deploy.subprocess.run",
               side_effect=CalledProcessError(returncode=1, cmd=["docker-compose", "build"])):
        with patch("docker.deploy.logger") as mock_logger:
            with pytest.raises(CalledProcessError):
                build_images()
    mock_logger.error.assert_called_once()


def test_build_images_angry_path_error_log_message_identifies_function():
    # Angry: R3 — error message should identify the failing function for diagnostics
    with patch("docker.deploy.subprocess.run", side_effect=Exception("Build failed")):
        with patch("docker.deploy.logger") as mock_logger:
            with pytest.raises(Exception):
                build_images()
    error_message = mock_logger.error.call_args[0][0]
    assert "build_images" in error_message


def test_build_images_angry_path_error_log_message_contains_exception_detail():
    # Angry: R3 — error message should include the underlying exception detail
    with patch("docker.deploy.subprocess.run", side_effect=Exception("No such service: daemon")):
        with patch("docker.deploy.logger") as mock_logger:
            with pytest.raises(Exception):
                build_images()
    error_message = mock_logger.error.call_args[0][0]
    assert "No such service: daemon" in error_message


# ── Delinquent Path ───────────────────────────────────────────────────────────

def test_build_images_delinquent_large_stdout_logged_without_truncation():
    # Delinquent: very large build output must be passed to logger unchanged
    large_output = "Step 1/50: FROM python:3.11\n" * 10_000
    result = MagicMock()
    result.stdout = large_output
    with patch("docker.deploy.subprocess.run", return_value=result):
        with patch("docker.deploy.logger") as mock_logger:
            build_images()
    logged_message = mock_logger.info.call_args[0][0]
    assert len(logged_message) == len(large_output)


def test_build_images_delinquent_stdout_with_special_characters_logged_as_is():
    # Delinquent: build output may contain ANSI codes, unicode, or control chars
    special_output = "\x1b[32mSuccessfully built\x1b[0m abc123\n日本語\n"
    result = MagicMock()
    result.stdout = special_output
    with patch("docker.deploy.subprocess.run", return_value=result):
        with patch("docker.deploy.logger") as mock_logger:
            build_images()
    logged_message = mock_logger.info.call_args[0][0]
    assert logged_message == special_output


def test_build_images_delinquent_subprocess_raises_on_malformed_compose_file():
    # Delinquent: malformed docker-compose.yml causes subprocess to raise;
    # CalledProcessError must propagate — R3
    with patch("docker.deploy.subprocess.run",
               side_effect=CalledProcessError(returncode=1, cmd=["docker-compose", "build"],
                                              stderr="ERROR: yaml.YAMLError")):
        with pytest.raises(CalledProcessError):
            build_images()


# ── Forgetful Path ────────────────────────────────────────────────────────────

def test_build_images_forgetful_timeout_expired_raises():
    # Forgetful: build exceeds timeout — SubprocessError propagates — R3
    import subprocess
    with patch("docker.deploy.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd=["docker-compose", "build"], timeout=300)):
        with pytest.raises(subprocess.TimeoutExpired):
            build_images()


def test_build_images_forgetful_timeout_expired_logs_error():
    # Forgetful: R3 — error must be logged before re-raising on timeout
    import subprocess
    with patch("docker.deploy.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd=["docker-compose", "build"], timeout=300)):
        with patch("docker.deploy.logger") as mock_logger:
            with pytest.raises(subprocess.TimeoutExpired):
                build_images()
    mock_logger.error.assert_called_once()


def test_build_images_forgetful_os_error_on_subprocess_raises():
    # Forgetful: OS-level failure (e.g., fork exhaustion) propagates — R3
    with patch("docker.deploy.subprocess.run", side_effect=OSError("Resource temporarily unavailable")):
        with pytest.raises(OSError):
            build_images()


def test_build_images_forgetful_memory_error_during_build_raises():
    # Forgetful: OOM during build propagates — R3
    with patch("docker.deploy.subprocess.run", side_effect=MemoryError("Out of memory")):
        with pytest.raises(MemoryError):
            build_images()


# ── Logging Guard ─────────────────────────────────────────────────────────────

def test_build_images_logging_error_not_called_on_success(mock_subprocess):
    # Logging: logger.error must not fire on a successful build
    with patch("docker.deploy.logger") as mock_logger:
        build_images()
    mock_logger.error.assert_not_called()


def test_build_images_logging_info_not_called_on_failure():
    # Logging: logger.info must not fire if subprocess raises before the log call
    with patch("docker.deploy.subprocess.run", side_effect=Exception("Build failed")):
        with patch("docker.deploy.logger") as mock_logger:
            with pytest.raises(Exception):
                build_images()
    mock_logger.info.assert_not_called()


def test_build_images_logging_info_called_exactly_once_on_success(mock_subprocess):
    # Logging: R2 — exactly one info log per successful build
    with patch("docker.deploy.logger") as mock_logger:
        build_images()
    assert mock_logger.info.call_count == 1


def test_build_images_logging_error_called_exactly_once_on_failure():
    # Logging: R3 — exactly one error log per failure
    with patch("docker.deploy.subprocess.run", side_effect=Exception("Build failed")):
        with patch("docker.deploy.logger") as mock_logger:
            with pytest.raises(Exception):
                build_images()
    assert mock_logger.error.call_count == 1
