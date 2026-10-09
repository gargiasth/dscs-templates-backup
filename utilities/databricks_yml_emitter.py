"""
Orion Launchpad — databricks.yml emitter.

Reads an Orion intake JSON and produces the top-level databricks.yml string
(bundle, variables, include glob, targets). The job definition itself lives
in a sibling file at resources/<project>_job.yml — see databricks_jobs_emitter.py.

Public entry point:
    build_databricks_yml(spec) -> str

CLI usage (from the repo root):
    python -m utilities.databricks_yml_emitter utilities/test_data/sample_OrionConfig.json

Writes to:
    utilities/test_output/databricks.yml
"""

import logging
import yaml

from utilities.emitter_helpers import _collect_variables
from utilities.logger import setup_logging

setup_logging()
log = logging.getLogger(__name__)


def build_databricks_yml(spec: dict) -> str:
    """Assemble the databricks.yml content from the Orion spec."""

    if "project" not in spec:
        raise ValueError("spec missing required field: 'project'")

    log.info("building databricks.yml for project %r", spec["project"])

    bundle = {"bundle": {"name": spec["project"]}}

    variables = _collect_variables(spec)
    if variables:
        bundle["variables"] = variables

    bundle["include"] = ["resources/*.yml"]

    workspace_url = spec.get("runtime", {}).get("workspace_url")
    if workspace_url:
        bundle["targets"] = {
            "dev": {
                "default": True,
                "workspace": {"host": workspace_url},
            }
        }

    log.info("databricks.yml built for project %r", spec["project"])
    return yaml.safe_dump(bundle, sort_keys=False, default_flow_style=False, width=120)


if __name__ == "__main__":
    print("MAIN BLOCK STARTED", flush=True)
    import sys
    import json
    from pathlib import Path

    if len(sys.argv) != 2:
        print("Usage: python -m utilities.databricks_yml_emitter <orion.json>", file=sys.stderr)
        sys.exit(1)

    print(f"reading {sys.argv[1]}", flush=True)
    spec = json.loads(Path(sys.argv[1]).read_text())

    print("building yml ...", flush=True)
    yml = build_databricks_yml(spec)

    out_path = Path(__file__).parent / "test_output" / "databricks.yml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yml)
    print(f"wrote {out_path}", flush=True)