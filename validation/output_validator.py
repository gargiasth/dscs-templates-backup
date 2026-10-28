"""
Orion Launchpad — output validation (run time, inside each task).

Orion never overwrites output. The user's script writes into a holding
folder next to the real output folder, and the files are moved in only if
none of them clash with files already there:

    staging = prepare_output(out)   before the script: out exists (created if
                                    missing) and is writable; a fresh, empty
                                    holding folder is made next to it
    ...the wrapper points the script at `staging` instead of `out`...
    finish_output(out, staging)     after the script: the holding folder has
                                    data, no file clashes with one already in
                                    out; then everything is moved into out

An output folder may already hold files from earlier runs; only a file with
the same name (and same subfolder) as a new one is a problem.

Platform-agnostic: it only uses ordinary file paths (Databricks volumes, or
Snowflake stages mounted into an SPCS container). Only the privilege named in
the error message differs per platform.

Public API:
    staging_path(out)                           -> Path
    prepare_output(out, platform="databricks")  -> Path (the holding folder)
    finish_output(out, staging)                 -> list[Path] (files moved in)
    OutputValidationError
"""

import logging
import re
import shutil
import tempfile
from pathlib import Path

from utilities.logger import setup_logging
from validation.input_validator import _files

setup_logging()
log = logging.getLogger(__name__)

STAGING_ROOT   = Path(tempfile.gettempdir()) / "orion_staging"   # local disk, e.g. /tmp/orion_staging
MARKER         = ".orion_write_check"   # written and deleted to prove a folder is writable
MAX_LISTED     = 5                      # clashing file names shown in the error

_WRITE_PRIVILEGE = {
    "databricks": "WRITE VOLUME on the volume",
    "snowflake":  "WRITE on the stage",
}


class OutputValidationError(Exception):
    """Raised when the output can't be written, stayed empty, or would overwrite files."""


def _privilege(platform: str) -> str:
    return _WRITE_PRIVILEGE.get(platform, "write access to the output folder")


def staging_path(out) -> Path:
    """The local holding folder for an output folder, named after its full path so two outputs never share one."""
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(out).strip("/\\")) or "output"
    return STAGING_ROOT / name


def _check_writable(folder: Path, platform: str) -> None:
    marker = folder / MARKER
    try:
        marker.write_text("ok", encoding="utf-8")
        marker.unlink()
    except OSError as e:
        raise OutputValidationError(
            f"Can't write to {folder}. Ask an admin for {_privilege(platform)}.") from e


# ── Before the script ────────────────────────────────────────────────────────

def prepare_output(out, platform: str = "databricks") -> Path:
    """Make sure the output folder exists and is writable; return a fresh holding folder."""
    out = Path(out)
    staging = staging_path(out)
    try:
        out.mkdir(parents=True, exist_ok=True)
        if staging.exists():
            shutil.rmtree(staging)               # left over from an earlier failed run; it's Orion's own
        staging.mkdir(parents=True)
    except OSError as e:
        raise OutputValidationError(
            f"Can't create the output folder {out}. Ask an admin for {_privilege(platform)}.") from e

    _check_writable(out, platform)
    _check_writable(staging, platform)
    log.info("output folder ready: %s (script writes to %s)", out, staging)
    return staging


# ── After the script ─────────────────────────────────────────────────────────

def finish_output(out, staging) -> list[Path]:
    """Check what the script wrote, refuse any clash, then move it all into the output folder."""
    out, staging = Path(out), Path(staging)
    new_files = [f for f in _files(staging) if f.name != MARKER] if staging.is_dir() else []

    if not any(f.stat().st_size > 0 for f in new_files):
        shutil.rmtree(staging, ignore_errors=True)
        raise OutputValidationError(
            f"The script finished but wrote nothing for {out}. Check that one of the script's "
            f"parameters uses this output folder, so Orion can point it at the holding folder.")

    rel = [f.relative_to(staging) for f in new_files]
    clashes = [r for r in rel if (out / r).exists()]
    if clashes:
        shown = ", ".join(r.as_posix() for r in clashes[:MAX_LISTED])
        more = f" and {len(clashes) - MAX_LISTED} more" if len(clashes) > MAX_LISTED else ""
        raise OutputValidationError(
            f"{len(clashes)} new file(s) have the same name as files already in {out}: {shown}{more}. "
            f"Nothing was overwritten. Remove or rename the old files, then rerun.")

    moved = []
    for src, r in zip(new_files, rel):
        dest = out / r
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved.append(dest)
    shutil.rmtree(staging, ignore_errors=True)
    log.info("moved %d file(s) into %s", len(moved), out)
    return moved