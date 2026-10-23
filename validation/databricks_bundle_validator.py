"""
Orion Launchpad — checks the generated bundle after the compiler writes it.

The spec validator checks what goes IN; this checks what came OUT. Every
problem here means the emitters disagree with each other (a compiler bug),
so the compiler stops instead of handing over a bundle that would fail at
`databricks bundle validate` or at run time.

Public API:
    validate_bundle(output_dir, jobs_yml, wrapper_dir) -> ValidationReport
    BundleValidationError
"""

import ast
import logging
import re
from pathlib import Path

import yaml

from utilities.logger import setup_logging
from validation.spec_validator import ValidationReport

setup_logging()
log = logging.getLogger(__name__)

DATABRICKS_YML = "databricks.yml"
VAR_REF_RE     = re.compile(r"\$\{var\.([A-Za-z0-9_-]+)\}")


class BundleValidationError(ValueError):
    """Raised by the compiler when the generated files don't line up."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"{len(errors)} problem(s) in the generated bundle "
                         f"(compiler bug, please report):\n  - " + "\n  - ".join(errors))


# ── Public API ───────────────────────────────────────────────────────────────

def validate_bundle(output_dir, jobs_yml, wrapper_dir) -> ValidationReport:
    """jobs_yml and wrapper_dir are relative to output_dir. Never raises."""
    output_dir  = Path(output_dir)
    jobs_path   = output_dir / jobs_yml
    wrapper_dir = output_dir / wrapper_dir
    log.info("validating bundle in %s", output_dir)
    report = ValidationReport()

    bundle = _load_yaml(output_dir / DATABRICKS_YML, report)
    jobs   = _load_yaml(jobs_path, report)
    if bundle is None or jobs is None:
        return report

    _check_include(bundle, output_dir, jobs_path, report)

    tasks, environments = _tasks_and_environments(jobs, report)
    used_wrappers = _check_tasks(tasks, environments, jobs_path, report)
    _check_orphan_wrappers(wrapper_dir, used_wrappers, report)
    _check_vars_declared(bundle, jobs_path, report)

    log.info("bundle validation: %d error(s), %d warning(s)",
             len(report.errors), len(report.warnings))
    return report


# ── Checks ───────────────────────────────────────────────────────────────────

def _load_yaml(path: Path, report):
    if not path.exists():
        report.error(path.name, "was not written")
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        report.error(path.name, f"is not valid YAML: {e}")
        return None
    if not isinstance(data, dict):
        report.error(path.name, "is empty or not a mapping")
        return None
    return data


def _check_include(bundle, output_dir, jobs_path, report) -> None:
    """databricks.yml's include: patterns must pick up the jobs YAML."""
    patterns = bundle.get("include") or []
    if not any(jobs_path in output_dir.glob(p) for p in patterns):
        report.error("databricks.yml.include",
                     f"{patterns} does not match {jobs_path.relative_to(output_dir).as_posix()}")


def _tasks_and_environments(jobs, report):
    tasks, environments = [], set()
    for job_name, job in ((jobs.get("resources") or {}).get("jobs") or {}).items():
        for env in job.get("environments") or []:
            environments.add(env.get("environment_key"))
        for task in job.get("tasks") or []:
            tasks.append(task)
    return tasks, environments


def _check_tasks(tasks, environments, jobs_path, report) -> set:
    """Unique keys, real dependencies, known environments, existing wrappers."""
    keys = [t.get("task_key") for t in tasks]
    seen, used_wrappers = set(), set()

    for task in tasks:
        key = task.get("task_key")
        where = f"task {key}"

        if not key:
            report.error("task", "has no task_key")
        elif key in seen:
            report.error(where, "task_key is used more than once")
        seen.add(key)

        for dep in task.get("depends_on") or []:
            dep_key = dep.get("task_key")
            if dep_key == key:
                report.error(where, "depends on itself")
            elif dep_key not in keys:
                report.error(where, f"depends on {dep_key!r}, which is not a task")

        env = task.get("environment_key")
        if env and env not in environments:
            report.error(where, f"environment_key {env!r} is not defined in the job")

        python_file = (task.get("spark_python_task") or {}).get("python_file")
        if not python_file:
            report.error(where, "has no spark_python_task.python_file")
            continue
        wrapper = (jobs_path.parent / python_file).resolve()
        used_wrappers.add(wrapper)
        if not wrapper.is_file():
            report.error(where, f"python_file {python_file} does not exist")
            continue
        try:
            ast.parse(wrapper.read_text(encoding="utf-8"), filename=str(wrapper))
        except SyntaxError as e:
            report.error(where, f"wrapper has a syntax error at line {e.lineno}: {e.msg}")

    _check_no_cycles(tasks, report)
    return used_wrappers


def _check_no_cycles(tasks, report) -> None:
    graph = {t.get("task_key"): [d.get("task_key") for d in t.get("depends_on") or []] for t in tasks}
    state = {}                                       # key -> "visiting" | "done"

    def visit(key, path):
        if state.get(key) == "done" or key not in graph:
            return
        if state.get(key) == "visiting":
            report.error("tasks", "dependency cycle: " + " -> ".join(path + [key]))
            return
        state[key] = "visiting"
        for dep in graph[key]:
            if dep != key:                           # self-dependency already reported
                visit(dep, path + [key])
        state[key] = "done"

    for key in graph:
        visit(key, [])


def _check_orphan_wrappers(wrapper_dir: Path, used_wrappers: set, report) -> None:
    if not wrapper_dir.is_dir():
        return
    for wrapper in sorted(wrapper_dir.glob("*.py")):
        if wrapper.resolve() not in used_wrappers:
            report.warn(wrapper.name, "no task uses this wrapper")


def _check_vars_declared(bundle, jobs_path, report) -> None:
    declared = set((bundle.get("variables") or {}).keys())
    used = set(VAR_REF_RE.findall(jobs_path.read_text(encoding="utf-8")))
    for var in sorted(used - declared):
        report.error(jobs_path.name, f"uses ${{var.{var}}}, which databricks.yml does not declare")