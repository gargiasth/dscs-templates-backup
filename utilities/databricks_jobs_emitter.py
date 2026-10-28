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
from pathlib import Path

import yaml

from utilities.emitter_helpers import (
    _var_safe,
    _var_ref,
    _task_key,
    _collect_variables,
    _preflight_params,
    _io_params,
    PREFLIGHT_KEY,
)
from utilities.logger import setup_logging

setup_logging()
log = logging.getLogger(__name__)


def _available_variables(spec: dict) -> set[str]:
    """Names of variables that databricks.yml will declare — used to validate refs."""
    return set((_collect_variables(spec) or {}).keys())


def _build_task(file, params, layer, stage_name, env_key, deps, wrapper_dir, wrapper_prefix):
    """One spark_python_task entry under resources.jobs.<project>.tasks."""
    if file.endswith(".sql"):                                          
        params = [_var_ref("catalog"), _var_ref("schema")] + params  

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


def _collect_tasks(spec: dict, env_key: str, wrapper_dir: str, wrapper_prefix: str) -> list[dict]:
    """One task per stage, built from the stage's entry_point (same source the wrapper generator uses)."""
    tasks = []
    stage_task_keys = {}  # stage_name -> task_keys it produced (for downstream deps)

    for stage in spec.get("stages", []):
        sname  = stage.get("name", "")
        slayer = stage.get("layer", "")

        # Any `auto` source means this stage waits on the stage named in `from`.
        deps = []
        for src in stage.get("sources", []):
            if src.get("data_upload_type") == "auto":
                deps.extend(stage_task_keys.get(src.get("from", ""), []))

        entry = stage.get("entry_point")
        if not isinstance(entry, dict) or not entry.get("file") or not entry.get("path"):
            continue
        if not entry["file"].endswith((".py", ".sql")):
            continue

        task, key = _build_task(
            file           = entry["file"],
            params         = list(entry.get("parameters", [])) + _io_params(spec, stage),
            layer          = slayer,
            stage_name     = sname,
            env_key        = env_key,
            deps           = deps,
            wrapper_dir    = wrapper_dir,
            wrapper_prefix = wrapper_prefix,
        )
        tasks.append(task)
        stage_task_keys[sname] = [key]

    return tasks


def _add_preflight(spec, tasks, env_key, wrapper_dir, wrapper_prefix) -> list[dict]:
    """Put the preflight task first; every task that waited on nothing now waits on it."""
    if not tasks:
        return tasks                        # nothing to protect, no preflight
    for task in tasks:
        if not task.get("depends_on"):
            task["depends_on"] = [{"task_key": PREFLIGHT_KEY}]
    preflight = {
        "task_key":        PREFLIGHT_KEY,
        "environment_key": env_key,
        "spark_python_task": {
            "python_file": f"{wrapper_dir}/{wrapper_prefix}{PREFLIGHT_KEY}.py",
            "parameters":  _preflight_params(spec),
        },
    }
    return [preflight] + tasks


ORION_DEPENDENCIES = ["sqlglot"]       # what Orion's own wrappers import (SQL translation)


def _read_requirements(path) -> list[str]:
    """Package lines from a requirements.txt: no comments, blanks, or pip options (-r, -e, --index-url)."""
    path = Path(path)
    if not path.is_file():
        log.warning("%s not found; the job environment gets only Orion's own packages", path)
        return []
    packages = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):
            log.warning("%s: skipped pip option %r (not supported in a job environment)", path, line)
            continue
        packages.append(line)
    log.info("read %d package(s) from %s", len(packages), path)
    return packages


def build_jobs_yml(spec: dict, wrapper_dir: str, wrapper_prefix: str,
                   requirements_path=None) -> str:
    """Assemble resources/<project>_job.yml content from the Orion spec.

    requirements_path: a requirements.txt whose packages the job environment
    installs. Orion's own (ORION_DEPENDENCIES) are always included; repeats are dropped.
    """

    if "project" not in spec:
        raise ValueError("spec missing required field: 'project'")

    log.info("building jobs yml for project %r", spec["project"])

    env_key = "default_env"
    packages = _read_requirements(requirements_path) if requirements_path else []
    tasks = _collect_tasks(spec, env_key, wrapper_dir, wrapper_prefix)
    tasks = _add_preflight(spec, tasks, env_key, wrapper_dir, wrapper_prefix)

    job = {
        "name": spec["project"],
        "environments": [{
            "environment_key": env_key,
            "spec": {
                "client": "3",            # TBD — not in intake yet
                "dependencies": list(dict.fromkeys(ORION_DEPENDENCIES + packages)),
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