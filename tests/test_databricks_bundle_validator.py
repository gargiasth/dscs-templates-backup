"""
Tests for validation/bundle_validator.py

Run from the repo root:
    pytest tests/test_bundle_validator.py

Each test builds a tiny bundle in tmp_path (databricks.yml, a jobs YAML and
wrappers), breaks one thing, and checks the validator reports it.
"""

import pytest
import yaml

from validation.databricks_bundle_validator import validate_bundle, BundleValidationError

JOBS = "resources/databricks_jobs.yml"
WRAPPERS = "utilities/wrappers"


def _task(key, deps=(), env="default_env", params=()):
    task = {
        "task_key": key,
        "environment_key": env,
        "spark_python_task": {"python_file": f"../{WRAPPERS}/run_{key}.py",
                              "parameters": list(params)},
    }
    if deps:
        task["depends_on"] = [{"task_key": d} for d in deps]
    return task


@pytest.fixture
def bundle(tmp_path):
    """A valid two-task bundle. Returns a helper to rewrite parts of it."""
    def write(tasks=None, variables=None, include=("resources/*.yml",), wrappers=None):
        tasks = tasks if tasks is not None else [
            _task("bronze_fetch_py", params=["${var.raw_subfolder_path}"]),
            _task("silver_etl_py", deps=["bronze_fetch_py"]),
        ]
        variables = variables if variables is not None else {"raw_subfolder_path": {"default": "/Volumes/c/s/v/raw"}}
        (tmp_path / "databricks.yml").write_text(yaml.safe_dump(
            {"bundle": {"name": "demo"}, "variables": variables, "include": list(include)}))
        (tmp_path / "resources").mkdir(exist_ok=True)
        (tmp_path / JOBS).write_text(yaml.safe_dump({"resources": {"jobs": {"demo": {
            "name": "demo",
            "environments": [{"environment_key": "default_env", "spec": {"client": "3"}}],
            "tasks": tasks}}}}))
        wdir = tmp_path / WRAPPERS
        wdir.mkdir(parents=True, exist_ok=True)
        for t in tasks if wrappers is None else wrappers:
            name = t["task_key"] if isinstance(t, dict) else t
            (wdir / f"run_{name}.py").write_text("print('ok')\n", encoding="utf-8")
        return tmp_path
    return write


def check(root):
    return validate_bundle(root, JOBS, WRAPPERS)


class TestHappyPath:

    def test_valid_bundle(self, bundle):
        report = check(bundle())
        assert report.errors == [] and report.warnings == []

    def test_error_is_a_value_error(self):
        assert issubclass(BundleValidationError, ValueError)


class TestFiles:

    def test_missing_databricks_yml(self, bundle):
        root = bundle()
        (root / "databricks.yml").unlink()
        assert any("was not written" in e for e in check(root).errors)

    def test_invalid_yaml(self, bundle):
        root = bundle()
        (root / JOBS).write_text("resources: [unclosed")
        assert any("not valid YAML" in e for e in check(root).errors)

    def test_include_does_not_match_jobs_yml(self, bundle):
        root = bundle(include=("other/*.yml",))
        assert any("does not match" in e for e in check(root).errors)


class TestTasks:

    def test_duplicate_task_key(self, bundle):
        root = bundle(tasks=[_task("a_py"), _task("a_py")])
        assert any("used more than once" in e for e in check(root).errors)

    def test_depends_on_missing_task(self, bundle):
        root = bundle(tasks=[_task("a_py", deps=["ghost"])])
        assert any("'ghost', which is not a task" in e for e in check(root).errors)

    def test_depends_on_itself(self, bundle):
        root = bundle(tasks=[_task("a_py", deps=["a_py"])])
        assert any("depends on itself" in e for e in check(root).errors)

    def test_dependency_cycle(self, bundle):
        root = bundle(tasks=[_task("a_py", deps=["b_py"]), _task("b_py", deps=["a_py"])])
        assert any("dependency cycle" in e for e in check(root).errors)

    def test_unknown_environment(self, bundle):
        root = bundle(tasks=[_task("a_py", env="gpu_env")])
        assert any("'gpu_env' is not defined" in e for e in check(root).errors)

    def test_missing_wrapper(self, bundle):
        root = bundle(tasks=[_task("a_py")], wrappers=[])
        assert any("does not exist" in e for e in check(root).errors)

    def test_wrapper_syntax_error(self, bundle):
        root = bundle(tasks=[_task("a_py")])
        (root / WRAPPERS / "run_a_py.py").write_text("def x(:\n")
        assert any("syntax error" in e for e in check(root).errors)

    def test_unused_wrapper_is_a_warning(self, bundle):
        root = bundle(tasks=[_task("a_py")], wrappers=["a_py", "old_py"])
        report = check(root)
        assert report.errors == []
        assert any("run_old_py.py" in w for w in report.warnings)


class TestVariables:

    def test_undeclared_var_in_jobs_yml(self, bundle):
        root = bundle(variables={})
        assert any("raw_subfolder_path" in e and "does not declare" in e for e in check(root).errors)