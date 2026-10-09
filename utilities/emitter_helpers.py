"""
Shared helpers for the Databricks emitters.

Both databricks_yml_emitter.py and databricks_jobs_emitter.py import from
here. This file does not configure logging — the importing module is
expected to call setup_logging() itself.
"""

import logging
import re

log = logging.getLogger(__name__)


def _var_safe(text: str) -> str:
    """Make a string safe to use as a bundle variable name segment."""
    return re.sub(r"[^a-z0-9_]+", "_", text.strip().lower()).strip("_") or "stage"


def _var_ref(name: str) -> str:
    """Format a bundle variable reference, e.g. ${var.foo}."""
    return "${var." + name + "}"


def _volume_path(uc: dict, subfolder: str) -> str:
    """Compose a Unity Catalog volume path from the UC block + subfolder name."""
    return f"/Volumes/{uc['catalog']}/{uc['schema']}/{uc['volume']}/{subfolder}"


def _task_key(layer: str, stage_name: str, identifier: str) -> str:
    """<layer>_<stage>_<identifier> — one convention for every task."""
    return f"{_var_safe(layer)}_{_var_safe(stage_name)}_{_var_safe(identifier)}"


def _collect_variables(spec: dict) -> dict:
    """Walk the spec and return the flat {var_name: {default: value}} dict
    that lands under `variables:` in databricks.yml.

    Used by both emitters — the yml emitter writes it out, the jobs emitter
    uses the key set to decide whether a param should be a ${var.X} ref or
    a literal fallback.
    """
    variables = {}

    # Unity Catalog block → catalog / schema / volume
    uc = spec.get("unity_catalog", {})
    for key in ("catalog", "schema", "volume"):
        if uc.get(key):
            variables[key] = {"default": uc[key]}

    for stage in spec.get("stages", []):
        sname = stage.get("name", "")

        # Every source that lands data in a subfolder gets a variable
        for src in stage.get("sources", []):
            if src.get("data_upload_type") in ("manual", "custom_script"):
                sub = src.get("subfolder_name")
                if sub:
                    variables[f"{_var_safe(sub)}_subfolder_path"] = {
                        "default": _volume_path(uc, sub)
                    }

        # Destination subfolder (volume type only)
        dest = stage.get("destination", {})
        if dest.get("type") == "volume":
            sub = dest.get("subfolder_name")
            if sub:
                variables[f"{_var_safe(sub)}_subfolder_path"] = {
                    "default": _volume_path(uc, sub)
                }

        # Scripts stay stage-prefixed (same script name may appear in two stages)
        for script in stage.get("scripts") or []:
            if not isinstance(script, dict):
                continue
            file = script.get("file")
            path = script.get("path")
            if sname and file and path:
                stem = file.replace(".py", "")
                variables[f"{_var_safe(sname)}_{_var_safe(stem)}_script_path"] = {"default": path}

    log.info("collected %d variables from spec", len(variables))
    return variables