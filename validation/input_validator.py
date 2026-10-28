"""
Orion Launchpad — input validation (run time, inside each task).

Runs at the start of a task, before the user's script or SQL. Two checks:
  1. every input folder exists and has at least one non-empty file;
  2. every file Orion recognises (.csv, .txt, .sql) inside those folders
     is readable and well-formed.

All problems are collected and reported together. Errors stop the task;
warnings are logged and the task carries on.

Platform-agnostic:
  - files are read through ordinary paths. Databricks volumes (/Volumes/...)
    and Snowflake stages mounted into an SPCS container are ordinary paths.
    (A Snowflake stored procedure reads stages through Snowpark instead; that
    needs a file layer, added with the Snowflake emitter.)
  - .sql files are translated for the `platform` passed in.

Public API:
    validate_inputs(inputs, max_rows=1000, platform="databricks") -> ValidationReport
    check_inputs(inputs, max_rows=1000, platform="databricks")    -> None, raises InputValidationError
    inputs = [(folder_path, filled_by), ...]   filled_by: who fills the folder,
             e.g. "upstream task bronze_fetch_get_py" or "manual upload"
"""

import csv
import logging
import os
from pathlib import Path

from utilities.logger import setup_logging
from validation.spec_validator import ValidationReport, _check_sql

setup_logging()
log = logging.getLogger(__name__)

CHECKED_EXTS = {".csv", ".txt", ".sql"}
MAX_ROWS     = 1000                      # rows checked per data file, after the header
MAX_ROW_ERRS = 10                        # row problems listed per file before summarising
SNIFF_BYTES  = 64 * 1024                 # how much of the file csv.Sniffer looks at
DELIMITERS   = ",\t|;"
BOM          = b"\xef\xbb\xbf"
PLATFORMS    = ("databricks", "snowflake")   # targets the .sql check can translate for


class InputValidationError(Exception):
    """Raised when the task's inputs aren't usable. Holds every error found."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"{len(errors)} problem(s) with this task's inputs:\n  - " + "\n  - ".join(errors))


# ── Public API ───────────────────────────────────────────────────────────────

def validate_inputs(inputs, max_rows: int = MAX_ROWS, platform: str = "databricks") -> ValidationReport:
    """Check every input folder and the files in it. Never raises."""
    report = ValidationReport()
    if platform not in PLATFORMS:
        report.error("platform", f"{platform!r} is not supported; choose one of {list(PLATFORMS)}")
        return report
    log.info("validating %d input folder(s) for %s", len(inputs), platform)

    for folder, filled_by in inputs:
        if not _check_folder(Path(folder), filled_by, report):
            continue                                      # nothing to look inside
        for path in sorted(_files(Path(folder))):
            _check_file(path, report, max_rows, platform)

    log.info("input validation: %d error(s), %d warning(s)",
             len(report.errors), len(report.warnings))
    return report


def check_inputs(inputs, max_rows: int = MAX_ROWS, platform: str = "databricks") -> None:
    """What the wrapper calls: validate, and stop the task if anything is wrong."""
    report = validate_inputs(inputs, max_rows, platform)
    if report.errors:
        raise InputValidationError(report.errors)


# ── Folders ──────────────────────────────────────────────────────────────────

def _files(folder: Path):
    """Every file under the folder, including subfolders (e.g. synpuf_raw/DE_1/...)."""
    for root, _dirs, names in os.walk(folder):
        for name in names:
            yield Path(root) / name


def _check_folder(folder: Path, filled_by: str, report) -> bool:
    """True if the folder exists and has at least one file larger than 0 bytes."""
    hint = _hint(filled_by)
    if not folder.is_dir():
        report.error(str(folder), f"not found. {hint}")
        return False
    if not any(p.stat().st_size > 0 for p in _files(folder)):
        report.error(str(folder), f"is empty. {hint}")
        return False
    log.info("input folder ok: %s", folder)
    return True


def _hint(filled_by: str) -> str:
    if filled_by.startswith("upstream"):
        return f"Check that the {filled_by} completed successfully."
    if filled_by == "manual upload":
        return "Upload the files for this folder before running the pipeline."
    return f"It should be filled by {filled_by}."


# ── Files ────────────────────────────────────────────────────────────────────

def _check_file(path: Path, report, max_rows: int, platform: str) -> None:
    ext = path.suffix.lower()
    if ext not in CHECKED_EXTS:
        log.info("skipped (not a type Orion checks): %s", path)
        return
    if path.stat().st_size == 0:
        report.warn(str(path), "file is empty")
        return

    with open(path, "rb") as f:
        if f.read(3) == BOM:
            log.info("byte-order mark found and accepted: %s", path)

    if ext == ".sql":
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            report.warn(str(path), "is not valid UTF-8; not checked")
            return
        _check_sql(text, str(path), report, platform)
    else:
        _check_delimited(path, report, max_rows)


def _check_delimited(path: Path, report, max_rows: int) -> None:
    """Header + up to max_rows rows. Read line by line, never the whole file."""
    where = str(path)
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            sample = f.read(SNIFF_BYTES)
            dialect = _sniff(sample, path)
            if dialect is None:
                return                                    # free text .txt, nothing to check
            f.seek(0)
            # .txt files are often logs a script writes for itself (e.g. concept_debug_log.txt):
            # check them, but a problem there is a warning, never a reason to stop the task
            strict = path.suffix.lower() == ".csv"
            _check_rows(csv.reader(f, dialect), where, report, max_rows, strict)
    except UnicodeDecodeError:
        report.warn(where, "is not valid UTF-8; not checked (some scripts read other encodings on purpose)")


def _sniff(sample: str, path: Path):
    """Detect the delimiter. Athena's OMOP 'csv' files are actually tab-separated."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=DELIMITERS)
    except csv.Error:
        if path.suffix.lower() == ".txt":
            log.info("skipped (no delimiter found, treated as plain text): %s", path)
            return None
        return csv.excel                                  # .csv with one column: plain commas


def _check_rows(reader, where, report, max_rows: int, strict: bool = True) -> None:
    problem = report.error if strict else report.warn      # .txt: warnings only
    header = next(reader, None)
    if not header:
        problem(where, "has no header row")
        return

    # header: no empty names, no repeats (case-insensitive)
    seen = {}
    for i, name in enumerate(header, start=1):
        clean = name.strip()
        if not clean:
            problem(where, f"header column {i} has no name")
        elif clean.lower() in seen:
            problem(where, f"header column {clean!r} appears more than once "
                                f"(columns {seen[clean.lower()]} and {i})")
        else:
            seen[clean.lower()] = i

    # rows: same field count as the header
    rows, bad = 0, 0
    for row in reader:
        if not row:                                       # blank line, e.g. at the end
            continue
        rows += 1
        if len(row) != len(header):
            bad += 1
            if bad <= MAX_ROW_ERRS:
                problem(where, f"line {reader.line_num}: {len(row)} field(s), "
                                    f"header has {len(header)}")
        if rows >= max_rows:
            break
    if bad > MAX_ROW_ERRS:
        problem(where, f"{bad - MAX_ROW_ERRS} more line(s) with the wrong number of fields")
    if rows == 0:
        report.warn(where, "has a header but no data rows")