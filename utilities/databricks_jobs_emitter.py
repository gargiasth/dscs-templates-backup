"""
Orion Launchpad — Databricks jobs YAML emitter.

Reads an Orion intake JSON and produces the resources/<project>_job.yml
string (resources, jobs, environments, tasks). Deployed alongside the
databricks.yml file emitted by databricks_yml_emitter.py.

Public entry point:
    build_jobs_yml(spec) -> str

CLI usage (from the repo root):
    python -m utilities.databricks_jobs_emitter utilities/test_data/sample_OrionConfig.json

Writes to:
    utilities/test_output/resources/databricks_jobs.yml
"""

import logging
import yaml

from utilities.emitter_helpers import (
    _var_safe,
    _var_ref,
    _task_key,
    _collect_variables,
)
from utilities.logger import setup_logging

setup_logging()
log = logging.getLogger(__name__)


def _available_variables(spec: dict) -> set[str]:
    """Names of variables that databricks.yml will declare — used to validate refs."""
    return set((_collect_variables(spec) or {}).keys())


def _build_task(file, params, path, layer, stage_name, env_key, deps, wrapper_dir, wrapper_prefix):
    """One spark_python_task entry under resources.jobs.<project>.tasks."""
    key = _task_key(layer, stage_name, file)

    task = {
        "task_key":        key,
        "environment_key": env_key,
        "spark_python_task": {
            "python_file": f"{wrapper_dir}/{wrapper_prefix}{key}.py",
            "parameters":  params,
        },
    }
    if deps:
        task["depends_on"] = [{"task_key": k} for k in deps]
    return task, key


def _collect_tasks(spec: dict, env_key: str, available_vars: set[str],
                   wrapper_dir: str, wrapper_prefix: str) -> list[dict]:
    """Walk every stage and emit one task per download script and one per transform script.

    For each task, the destination subfolder path is auto-prepended to the parameters.
    User-provided parameters follow after.
    """
    tasks = []
    stage_task_keys = {}  # stage_name -> list of task_keys it produced (for downstream deps)

    for stage in spec.get("stages", []):
        sname  = stage.get("name", "")
        slayer = stage.get("layer", "")

        # ── Upstream dependencies ─────────────────────────────────────────
        # Any `auto` source means this stage waits on the stage named in `from`.
        deps = []
        for src in stage.get("sources", []):
            if src.get("data_upload_type") == "auto":
                deps.extend(stage_task_keys.get(src.get("from", ""), []))

        my_keys = []

        # ── Download tasks ────────────────────────────────────────────────
        # One task per script listed under a custom_script source.
        # The source's output subfolder path is auto-prepended as the first parameter.
        for src in stage.get("sources", []):
            if src.get("data_upload_type") != "custom_script":
                continue

            sub = src.get("subfolder_name", "")
            sub_var = f"{_var_safe(sub)}_subfolder_path" if sub else None
            auto_params = [_var_ref(sub_var)] if sub_var and sub_var in available_vars else []

            scripts = src.get("scripts") or []
            if isinstance(scripts, str):   # "scripts_default" placeholder — skip
                continue

            for script in scripts:
                if not isinstance(script, dict):
                    continue
                file = script.get("file")
                if not file:
                    continue

                user_params = script.get("parameters", [])
                task, key = _build_task(
                    file       = file,
                    params     = auto_params + user_params,
                    path       = script.get("path", f"../src/{file}"),
                    layer      = slayer,
                    stage_name = sname,
                    env_key    = env_key,
                    deps       = deps,
                    wrapper_dir    = wrapper_dir,
                    wrapper_prefix = wrapper_prefix,
                )
                tasks.append(task)
                my_keys.append(key)

        # ── Transform tasks ───────────────────────────────────────────────
        # One task per stage-level script. The stage's output subfolder path
        # is auto-prepended as the first parameter.
        scripts = stage.get("scripts") or []
        if isinstance(scripts, str):
            scripts = []

        dest = stage.get("destination", {})
        auto_params = []
        if dest.get("type") == "volume":
            dest_sub = dest.get("subfolder_name")
            if dest_sub:
                dest_var = f"{_var_safe(dest_sub)}_subfolder_path"
                if dest_var in available_vars:
                    auto_params = [_var_ref(dest_var)]

        for script in scripts:
            if not isinstance(script, dict):
                continue
            file = script.get("file")
            if not file:
                continue

            script_var = f"{_var_safe(sname)}_{_var_safe(file.replace('.py', ''))}_script_path"
            if script_var in available_vars:
                python_file = _var_ref(script_var)
            else:
                python_file = script.get("path", f"../src/{file}")

            user_params = script.get("parameters", [])
            task, key = _build_task(
                file       = file,
                params     = auto_params + user_params,
                path       = python_file,
                layer      = slayer,
                stage_name = sname,
                env_key    = env_key,
                deps       = deps,
                wrapper_dir    = wrapper_dir,
                wrapper_prefix = wrapper_prefix,
            )
            tasks.append(task)
            my_keys.append(key)

        stage_task_keys[sname] = my_keys

    return tasks


def build_jobs_yml(spec: dict, wrapper_dir: str, wrapper_prefix: str) -> str:
    """Assemble resources/<project>_job.yml content from the Orion spec."""

    if "project" not in spec:
        raise ValueError("spec missing required field: 'project'")

    log.info("building jobs yml for project %r", spec["project"])

    env_key = "default_env"
    available_vars = _available_variables(spec)
    tasks = _collect_tasks(spec, env_key, available_vars, wrapper_dir, wrapper_prefix)

    job = {
        "name": spec["project"],
        "environments": [{
            "environment_key": env_key,
            "spec": {
                "client": "3",            # TBD — not in intake yet
                "dependencies": [],       # TBD — not in intake yet
            },
        }],
        "tasks": tasks,
    }

    bundle = {"resources": {"jobs": {spec["project"]: job}}}

    log.info("jobs yml built for project %r (%d tasks)", spec["project"], len(tasks))
    return yaml.safe_dump(bundle, sort_keys=False, default_flow_style=False, width=120)


if __name__ == "__main__":
    print("MAIN BLOCK STARTED", flush=True)
    import sys
    import json
    from pathlib import Path, PurePosixPath
    from utilities.compiler import RESOURCES_DIR, WRAPPER_DIR, WRAPPER_PREFIX

    if len(sys.argv) != 2:
        print("Usage: python -m utilities.databricks_jobs_emitter <orion.json>", file=sys.stderr)
        sys.exit(1)

    print(f"reading {sys.argv[1]}", flush=True)
    spec = json.loads(Path(sys.argv[1]).read_text())

    print("building yml ...", flush=True)
    wrapper_ref = PurePosixPath(*[".."] * len(RESOURCES_DIR.parts), *WRAPPER_DIR.parts).as_posix()
    yml = build_jobs_yml(spec, wrapper_ref, WRAPPER_PREFIX)

    out_path = Path(__file__).parent / "test_output" / "resources" / "databricks_jobs.yml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yml)
    print(f"wrote {out_path}", flush=True)