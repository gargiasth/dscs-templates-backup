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


def _volume_path(uc: dict, subfolder: str, volume: str | None = None) -> str:
    """Compose a Unity Catalog volume path from the UC block + subfolder name.
    `volume` overrides the default volume, for folders that live in another one."""
    return f"/Volumes/{uc['catalog']}/{uc['schema']}/{volume or uc['volume']}/{subfolder}"


def _task_key(layer: str, stage_name: str, identifier: str) -> str:
    """<layer>_<stage>_<identifier> — one convention for every task."""
    return f"{_var_safe(layer)}_{_var_safe(stage_name)}_{_var_safe(identifier)}"


PREFLIGHT_KEY = "orion_preflight"     # task key of the job-start check; wrapper is run_orion_preflight.py


ORION_FOLDER = "ORION_FOLDER"    # ORION_FOLDER=<folder> — created by the preflight if missing


def _preflight_params(spec: dict) -> list[str]:
    """Parameters for the preflight task: catalog, schema, every volume, then every folder.

    The main volume is a variable; extra volumes from unity_catalog.folders
    are passed by name (they have no variable of their own). Every folder the
    spec names (registry, inputs, outputs) is passed as ORION_FOLDER=${var.X}.
    """
    uc = spec.get("unity_catalog", {})
    params = [_var_ref("catalog"), _var_ref("schema"), _var_ref("volume")]
    extra = []
    for folder in uc.get("folders") or []:
        vol = (folder.get("volume") or "").strip()
        if vol and vol != uc.get("volume") and vol not in extra:
            extra.append(vol)
    folders = [f"{ORION_FOLDER}={_var_ref(name)}"
               for name in _collect_variables(spec) if name.endswith("_subfolder_path")]
    return params + extra + folders


ORION_INPUT  = "ORION_INPUT"     # ORION_INPUT=<folder>|<who fills it>  — checked before the script
ORION_OUTPUT = "ORION_OUTPUT"    # ORION_OUTPUT=<folder>                — checked before and after


def _dest_subfolder(stage) -> str | None:
    """The volume subfolder a stage writes to, if it has one."""
    dest = (stage or {}).get("destination") or {}
    if isinstance(dest, dict) and dest.get("type") == "volume":
        return (dest.get("subfolder_name") or "").strip() or None
    return None


def _io_params(spec: dict, stage: dict) -> list[str]:
    """Extra task parameters telling the wrapper which folders to check.

    Inputs come from the stage's sources:
      auto   -> the upstream stage's output folder (only if it writes to a volume subfolder)
      manual -> that folder
    Output is the stage's own volume destination subfolder. Every path is a
    ${var.X} reference, so a target can still override it. The wrapper reads
    and removes these before running the script.
    """
    variables = _collect_variables(spec)
    by_name = {s.get("name"): s for s in spec.get("stages", []) if isinstance(s, dict)}

    def ref(sub):
        name = f"{_var_safe(sub)}_subfolder_path"
        return _var_ref(name) if name in variables else None

    params = []
    for src in stage.get("sources") or []:
        kind = src.get("data_upload_type")
        if kind == "auto":
            up = by_name.get(src.get("from"))
            sub = _dest_subfolder(up)
            if sub and ref(sub):
                entry = up.get("entry_point")
                who = (f"upstream task {_task_key(up.get('layer', ''), up['name'], entry['file'])}"
                       if isinstance(entry, dict) and entry.get("file") else f"upstream stage {up['name']}")
                params.append(f"{ORION_INPUT}={ref(sub)}|{who}")
        elif kind == "manual":
            sub = (src.get("subfolder_name") or "").strip()
            if sub and ref(sub):
                params.append(f"{ORION_INPUT}={ref(sub)}|manual upload")

    out = _dest_subfolder(stage)
    if out and ref(out):
        params.append(f"{ORION_OUTPUT}={ref(out)}")
    return params


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

    # Folders declared up front in the intake (unity_catalog.folders).
    # Each one may live in its own volume. Remember which, so a stage that
    # uses the same folder name gets the same path.
    folder_volume = {}
    for folder in uc.get("folders") or []:
        sub = (folder.get("subfolder") or "").strip()
        vol = (folder.get("volume") or "").strip()
        if sub and vol:
            folder_volume[sub] = vol
            variables[f"{_var_safe(sub)}_subfolder_path"] = {
                "default": _volume_path(uc, sub, vol)
            }

    for stage in spec.get("stages", []):
        sname = stage.get("name", "")

        # Every source that lands data in a subfolder gets a variable
        for src in stage.get("sources", []):
            if src.get("data_upload_type") in ("manual", "custom_script"):
                sub = src.get("subfolder_name")
                if sub:
                    variables[f"{_var_safe(sub)}_subfolder_path"] = {
                        "default": _volume_path(uc, sub, folder_volume.get(sub))
                    }

        # Destination subfolder (volume type only)
        dest = stage.get("destination", {})
        if dest.get("type") == "volume":
            sub = dest.get("subfolder_name")
            if sub:
                variables[f"{_var_safe(sub)}_subfolder_path"] = {
                    "default": _volume_path(uc, sub, folder_volume.get(sub))
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