"""
Orion Launchpad — generates one Python wrapper file per stage.

The wrapper is what Databricks actually runs. It connects to the user's
entry-point:
  - .py  → wrapper subprocess-runs the script
  - .sql → wrapper reads, translates, and executes via spark.sql()

Wrapper filename matches the task_key so emitter and generator agree:
    run_<task_key>.py
"""

import json
import logging
from pathlib import Path

from utilities.emitter_helpers import _task_key
from utilities.logger import setup_logging

setup_logging()
log = logging.getLogger(__name__)


def produce_wrapper(stage: dict, wrapper_depth: int) -> str | None:
    """Return wrapper source code for one stage, or None to skip."""
    entry = stage.get("entry_point")
    if not isinstance(entry, dict):
        return None

    script_path = entry.get("path")
    if not script_path:
        return None

    file_name  = entry.get("file", script_path)
    stage_name = stage.get("name", "unnamed")
    repo_root  = "Path(__file__)" + ".parent" * (wrapper_depth + 1)

    if file_name.endswith(".py"):
        return _PY_TEMPLATE.format(
            stage_name=stage_name,
            script_file=file_name,
            script_path=script_path,
            repo_root=repo_root,
        )

    if file_name.endswith(".sql"):
        return _SQL_TEMPLATE.format(
            stage_name=stage_name,
            sql_file=file_name,
            sql_path=script_path,
            repo_root=repo_root,
        )

    log.warning("stage %r: unsupported extension %r", stage_name, file_name)
    return None


def write_all_wrappers(spec: dict, output_dir, wrapper_prefix: str, wrapper_depth: int) -> list[Path]:
    """Write a wrapper for every stage. Returns the paths written."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for stage in spec.get("stages", []):
        code = produce_wrapper(stage, wrapper_depth)
        if code is None:
            continue

        task_key = _task_key(
            stage.get("layer", ""),
            stage["name"],
            stage["entry_point"]["file"],
        )
        path = output_dir / f"{wrapper_prefix}{task_key}.py"
        path.write_text(code, encoding="utf-8")
        written.append(path)
        log.info("wrote %s", path)

    return written


# ── Templates ────────────────────────────────────────────────────────────────

_PY_TEMPLATE = '''"""Wrapper for stage: {stage_name} — entry-point: {script_file}"""
import subprocess, sys
from pathlib import Path

_REPO_ROOT = {repo_root}
_SCRIPT = _REPO_ROOT / "{script_path}"

subprocess.run([sys.executable, str(_SCRIPT), *sys.argv[1:]], check=True)
'''

_SQL_TEMPLATE = '''"""Wrapper for stage: {stage_name} — entry-point: {sql_file}"""
from pathlib import Path
from pyspark.sql import SparkSession

from utilities.sql_read import read_sql_file
from utilities.sql_translate import translate

spark = SparkSession.builder.getOrCreate()
_SQL_PATH = {repo_root} / "{sql_path}"

for item in translate(read_sql_file(_SQL_PATH), read="postgres", dialect="databricks"):
    if not item["unsupported_reason"]:
        spark.sql(item["sql"])
'''


if __name__ == "__main__":
    import argparse
    from utilities.compiler import WRAPPER_DIR, WRAPPER_PREFIX

    parser = argparse.ArgumentParser(description="Generate wrappers for an orion.json spec.")
    parser.add_argument("spec_path", help="Path to orion.json")
    parser.add_argument("output_dir", help="Where to write wrappers")
    args = parser.parse_args()

    spec = json.loads(Path(args.spec_path).read_text(encoding="utf-8"))
    for p in write_all_wrappers(spec, Path(args.output_dir), WRAPPER_PREFIX, len(WRAPPER_DIR.parts)):
        print(p)