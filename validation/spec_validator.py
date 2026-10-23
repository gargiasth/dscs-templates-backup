"""
Orion Launchpad — config-time validation of an orion.json spec.

Runs on your machine, before the compiler writes any bundle file. It checks
the spec's structure, that every ${var.X} a parameter uses will be declared,
and — when given repo_root — that each entry-point file exists and is usable
(.py parses, .sql translates). Nothing here talks to Databricks. Whether the
catalog, schema and volumes actually exist is checked at job start.

Every problem is collected in one pass, so the user sees them all at once:
    errors   -> the compiler stops and writes nothing
    warnings -> logged; compiling continues

Public API:
    validate_spec(spec, repo_root=None) -> ValidationReport
    SpecValidationError
"""

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from utilities.emitter_helpers import _collect_variables, _var_safe
from utilities.logger import setup_logging

setup_logging()
log = logging.getLogger(__name__)

NAME_RE       = re.compile(r"^[A-Za-z0-9_-]+$")     # catalog, schema, volume, folders, project
LAYER_TYPES   = {"bronze", "silver", "gold", "custom"}
ENTRY_EXTS    = (".py", ".sql")
DEST_TYPES    = {"volume", "tables"}
NO_ENTRY      = "entry_point_default"                  # intake sentinel: layer has no script yet
VAR_REF_RE    = re.compile(r"\$\{var\.([A-Za-z0-9_-]+)\}")  # a well-formed ${var.name}
BAD_REF_RE    = re.compile(r"\$\{|\{var\.|\$var\.")       # what's left of a broken one
SQL_READ      = "postgres"                             # same dialects the SQL wrapper uses
SQL_TARGET    = "databricks"


class SpecValidationError(ValueError):
    """Raised by the compiler when the spec has errors. Holds every error found."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"{len(errors)} problem(s) in the spec:\n  - " + "\n  - ".join(errors))


@dataclass
class ValidationReport:
    errors:   list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")
        log.error("%s: %s", where, msg)

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")
        log.warning("%s: %s", where, msg)


# ── Public API ───────────────────────────────────────────────────────────────

def validate_spec(spec: dict, repo_root: str | Path | None = None) -> ValidationReport:
    """Check the spec. Never raises — returns every problem found.

    repo_root: folder that entry_point.path is relative to. When None, the
    file checks are skipped and only the spec's structure is checked.
    """
    log.info("validating spec")
    report = ValidationReport()
    if not isinstance(spec, dict):
        report.error("spec", "must be a JSON object")
        return report

    _check_project(spec, report)
    _check_runtime(spec, report)
    _check_unity_catalog(spec, report)
    _check_stages(spec, report, repo_root)
    _check_var_refs(spec, report)

    log.info("spec validation: %d error(s), %d warning(s)",
             len(report.errors), len(report.warnings))
    return report


# ── Checks ───────────────────────────────────────────────────────────────────

def _is_placeholder(value) -> bool:
    """The intake writes '<field>_default' when a field was left empty."""
    return isinstance(value, str) and value.endswith("_default")


def _check_name(report, where, value, required=True) -> None:
    if value in (None, ""):
        if required:
            report.error(where, "is required")
        return
    if _is_placeholder(value):
        report.error(where, f"is still the placeholder {value!r}; fill it in at intake")
    elif not isinstance(value, str) or not NAME_RE.match(value):
        report.error(where, f"{value!r} must use only letters, digits, '_' and '-'")


def _check_project(spec, report) -> None:
    _check_name(report, "project", spec.get("project"))


def _check_runtime(spec, report) -> None:
    url = (spec.get("runtime") or {}).get("workspace_url")
    if url in (None, ""):
        report.warn("runtime.workspace_url", "not set; databricks.yml will have no target")
    elif _is_placeholder(url):
        report.error("runtime.workspace_url", f"is still the placeholder {url!r}")
    elif not str(url).startswith("https://"):
        report.error("runtime.workspace_url", f"{url!r} must start with https://")


def _check_unity_catalog(spec, report) -> None:
    uc = spec.get("unity_catalog")
    if not isinstance(uc, dict):
        report.error("unity_catalog", "is required")
        return
    for key in ("catalog", "schema", "volume"):
        _check_name(report, f"unity_catalog.{key}", uc.get(key))

    seen = set()
    for i, folder in enumerate(uc.get("folders") or []):
        where = f"unity_catalog.folders[{i}]"
        if not isinstance(folder, dict):
            report.error(where, "must be an object with 'volume' and 'subfolder'")
            continue
        _check_name(report, f"{where}.volume", folder.get("volume"))
        sub = folder.get("subfolder")
        _check_name(report, f"{where}.subfolder", sub)
        if sub in seen:
            report.error(f"{where}.subfolder", f"{sub!r} is declared more than once")
        seen.add(sub)


def _check_stages(spec, report, repo_root=None) -> None:
    stages = spec.get("stages")
    if stages is None:
        report.error("stages", "is required (use [] for none)")
        return
    if not isinstance(stages, list):
        report.error("stages", "must be a list")
        return

    earlier = set()          # names of stages already seen, for upstream checks
    keys_seen = {}           # _var_safe(name) -> original name, for collisions
    all_names = {s.get("name") for s in stages if isinstance(s, dict)}

    for i, stage in enumerate(stages):
        if not isinstance(stage, dict):
            report.error(f"stages[{i}]", "must be an object")
            continue
        name = stage.get("name")
        where = f"stages[{i}] ({name})" if name else f"stages[{i}]"

        # name: present, and unique once turned into a task-key segment
        if not name or not str(name).strip():
            report.error(where, "has no name")
        else:
            key = _var_safe(str(name))
            if key in keys_seen:
                report.error(where, f"name {name!r} clashes with {keys_seen[key]!r} "
                                    f"(both become {key!r} in task keys)")
            keys_seen.setdefault(key, name)

        # layer
        layer = stage.get("layer")
        if layer not in LAYER_TYPES:
            report.error(f"{where}.layer", f"{layer!r} must be one of {sorted(LAYER_TYPES)}")

        _check_entry_point(stage.get("entry_point"), where, report, repo_root)
        _check_sources(stage.get("sources"), where, earlier, all_names, report)
        _check_destination(stage.get("destination"), where, report)

        if name:
            earlier.add(name)


def _check_entry_point(entry, where, report, repo_root=None) -> None:
    if entry in (None, NO_ENTRY):
        report.warn(f"{where}.entry_point", "not set; this stage will produce no task")
        return
    if not isinstance(entry, dict):
        report.error(f"{where}.entry_point", "must be an object with 'file' and 'path'")
        return
    file, path = entry.get("file"), entry.get("path")
    if not file:
        report.error(f"{where}.entry_point.file", "is required")
    elif not str(file).endswith(ENTRY_EXTS):
        report.error(f"{where}.entry_point.file", f"{file!r} must be a .py or .sql file")
    if not path:
        report.error(f"{where}.entry_point.path", "is required")
    elif file and not str(path).replace("\\", "/").endswith("/" + file) and path != file:
        report.warn(f"{where}.entry_point", f"path {path!r} does not end with file {file!r}")
    params = entry.get("parameters", [])
    if not isinstance(params, list) or not all(isinstance(p, str) for p in params):
        report.error(f"{where}.entry_point.parameters", "must be a list of strings")

    # Only look on disk when we were told where to look and the path is usable.
    if repo_root is not None and path and str(file).endswith(ENTRY_EXTS):
        _check_entry_file(Path(repo_root) / str(path), f"{where}.entry_point.path", report)


def _check_entry_file(full_path: Path, where, report) -> None:
    """The entry-point file exists, is a file, is readable text, and (.py) parses."""
    if not full_path.exists():
        report.error(where, f"file not found: {full_path}")
        return
    if not full_path.is_file():
        report.error(where, f"is a folder, not a file: {full_path}")
        return
    try:
        text = full_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        report.error(where, f"is not UTF-8 text: {full_path}")
        return
    if not text.strip():
        report.warn(where, f"file is empty: {full_path}")
        return
    if full_path.suffix == ".py":
        try:
            ast.parse(text, filename=str(full_path))   # parse only, never runs it
        except SyntaxError as e:
            report.error(where, f"syntax error at line {e.lineno}: {e.msg}")
    elif full_path.suffix == ".sql":
        _check_sql(text, where, report)


def _check_sql(text, where, report, platform: str = SQL_TARGET) -> None:
    """Translate the file the same way the SQL wrapper will, and look at the result.

    platform: the target the SQL will run on ("databricks" or "snowflake").
    """
    from utilities.sql_translate import translate   # imported here: pulls in sqlglot

    try:
        results = translate(text, read=SQL_READ, dialect=platform)
    except Exception as e:                           # sqlglot raises several types
        report.error(where, f"SQL could not be translated: {e}")
        return

    runnable = [r for r in results if not r["unsupported_reason"]]
    for r in results:
        if r["unsupported_reason"]:
            preview = r["sql"].replace("\n", " ")[:60]
            report.warn(where, f"will be skipped on {platform} ({r['unsupported_reason']}): {preview}")
    if not runnable:
        report.error(where, f"SQL file has no statements that can run on {platform}")


def _check_var_refs(spec, report) -> None:
    """Every ${var.X} in an entry-point parameter must be declared in databricks.yml."""
    try:
        declared = _collect_variables(spec)          # the exact set the yml emitter writes
    except Exception:
        return                                       # spec too broken; structure errors already say why

    for i, stage in enumerate(spec.get("stages") or []):
        if not isinstance(stage, dict) or not isinstance(stage.get("entry_point"), dict):
            continue
        params = stage["entry_point"].get("parameters") or []
        if not isinstance(params, list):
            continue                                 # already reported by _check_entry_point
        name = stage.get("name")
        where = f"stages[{i}] ({name}).entry_point.parameters" if name else f"stages[{i}].entry_point.parameters"

        for param in params:
            if not isinstance(param, str):
                continue
            for var in VAR_REF_RE.findall(param):
                if var not in declared:
                    report.error(where, f"{param!r} uses ${{var.{var}}}, which is not declared "
                                        f"(add the folder in the intake or fix the name)")
            if BAD_REF_RE.search(VAR_REF_RE.sub("", param)):
                report.error(where, f"{param!r} has a malformed variable reference; "
                                    f"use ${{var.name}}")

            value = param.split("=", 1)[1] if re.match(r"^[A-Z_][A-Z0-9_]*=", param) else param
            for var, info in declared.items():
                default = str(info.get("default", ""))
                if default.startswith("/Volumes/") and (value == default or value.startswith(default + "/")):
                    report.warn(where, f"{param!r} hard-codes a path; use ${{var.{var}}} instead")
                    break


def _check_sources(sources, where, earlier, all_names, report) -> None:
    if sources is None:
        return
    if not isinstance(sources, list):
        report.error(f"{where}.sources", "must be a list")
        return
    for j, src in enumerate(sources):
        swhere = f"{where}.sources[{j}]"
        if not isinstance(src, dict):
            report.error(swhere, "must be an object")
            continue
        kind = src.get("data_upload_type")
        if kind == "auto":
            up = src.get("from")
            if up not in all_names:
                report.error(swhere, f"upstream stage {up!r} does not exist")
            elif up not in earlier:
                report.error(swhere, f"upstream stage {up!r} must come before this stage")
        elif kind in ("manual", "custom_script"):
            _check_name(report, f"{swhere}.subfolder_name", src.get("subfolder_name"),
                        required=(kind == "manual"))
        else:
            report.error(f"{swhere}.data_upload_type",
                         f"{kind!r} must be 'auto', 'manual' or 'custom_script'")


def _check_destination(dest, where, report) -> None:
    if dest is None:
        return
    if not isinstance(dest, dict) or dest.get("type") not in DEST_TYPES:
        report.error(f"{where}.destination.type", f"must be one of {sorted(DEST_TYPES)}")
        return
    if dest["type"] == "volume":
        _check_name(report, f"{where}.destination.subfolder_name",
                    dest.get("subfolder_name"), required=False)
    elif _is_placeholder(dest.get("tables")):
        report.error(f"{where}.destination.tables", "no tables selected")