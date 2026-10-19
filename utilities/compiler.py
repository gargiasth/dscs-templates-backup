"""
Orion Launchpad — bundle compiler.

Takes an orion.json spec, runs the generators and emitters in order,
produces a working Databricks bundle in the output directory.

Think of this like `gcc`: the compiler is the entry point, each step
(wrapper generator, YAML emitters) is a stage that happens inside it.
Users run one command and get a complete bundle.

Order matters:
    1. Wrappers first — the jobs YAML references them, so they must
       exist on disk before the YAML lands.
    2. databricks.yml second — bundle metadata, no cross-references.
    3. jobs YAML last — references wrappers by path.

Public entry point:
    compile_bundle(spec_path, output_dir) -> dict

CLI usage:
    python -m utilities.compiler <orion.json> <output_dir>
"""

import json
import logging
from pathlib import Path

from utilities.logger import setup_logging
from utilities.generate_wrapper import write_all_wrappers
from utilities.databricks_yml_emitter import build_databricks_yml
from utilities.databricks_jobs_emitter import build_jobs_yml

setup_logging()
log = logging.getLogger(__name__)


# ── Public API ───────────────────────────────────────────────────────────────

def compile_bundle() -> dict:
    """Compile an orion.json spec into a Databricks bundle at output_dir.

    Produces this tree:
        <output_dir>/
        ├── databricks.yml
        ├── resources/
        │   └── databricks_jobs.yml
        └── utilities/
            └── wrappers/
                ├── run_<stage>.py
                └── ...

    Returns a dict of paths written:
        {
            "wrappers":      [Path, ...],
            "databricks_yml": Path,
            "jobs_yml":       Path,
        }
    """
    spec_path  = Path(r"C:\Users\GargiAsthana\OneDrive - Axle\Projects\Templates\dscs-templates\tests\test_data\sample_OrionConfig.json")
    output_dir = Path(r"C:\Users\GargiAsthana\OneDrive - Axle\Projects\Templates\dscs-templates\tests\test_output")
    output_dir.mkdir(parents=True, exist_ok=True)

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    log.info("compiling %s → %s", spec_path, output_dir)

    # ── Step 1: wrappers ──
    # The jobs YAML will reference these by path, so write them first.
    wrapper_paths = _emit_wrappers(spec, output_dir)

    # ── Step 2: databricks.yml ──
    # Bundle metadata — name, targets, variables. No cross-refs.
    databricks_yml_path = _emit_databricks_yml(spec, output_dir)

    # ── Step 3: jobs YAML ──
    # Task definitions. Each task points at a wrapper from step 1.
    jobs_yml_path = _emit_jobs_yml(spec, output_dir)

    log.info("compile complete: %d wrapper(s), 2 YAML file(s)",
             len(wrapper_paths))

    return {
        "wrappers":       wrapper_paths,
        "databricks_yml": databricks_yml_path,
        "jobs_yml":       jobs_yml_path,
    }


# ── Internal steps ───────────────────────────────────────────────────────────
# One private function per compiler step. Each takes the spec + the root
# output_dir and knows where its own output goes.

def _emit_wrappers(spec: dict, output_dir: Path) -> list[Path]:
    wrapper_dir = output_dir / "utilities" / "wrappers"
    written = write_all_wrappers(spec, wrapper_dir)
    log.info("step 1: wrote %d wrapper(s) → %s", len(written), wrapper_dir)
    return written


def _emit_databricks_yml(spec: dict, output_dir: Path) -> Path:
    yml_content = build_databricks_yml(spec)
    yml_path = output_dir / "databricks.yml"
    yml_path.write_text(yml_content, encoding="utf-8")
    log.info("step 2: wrote %s", yml_path)
    return yml_path


def _emit_jobs_yml(spec: dict, output_dir: Path) -> Path:
    jobs_content = build_jobs_yml(spec)
    jobs_path = output_dir / "resources" / "databricks_jobs.yml"
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    jobs_path.write_text(jobs_content, encoding="utf-8")
    log.info("step 3: wrote %s", jobs_path)
    return jobs_path


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Compile an orion.json spec into a Databricks bundle.",
    )
    parser.add_argument(
        "spec_path",
        nargs="?",
        default="utilities/test_data/sample_OrionConfig.json",
        help="Path to orion.json (default: utilities/test_data/sample_OrionConfig.json)",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="utilities/test_output",
        help="Where to write the bundle (default: utilities/test_output)",
    )
    args = parser.parse_args()

    result = compile_bundle(args.spec_path, args.output_dir)

    print(f"\nCompiled bundle:")
    print(f"  databricks.yml:        {result['databricks_yml']}")
    print(f"  resources/jobs.yml:    {result['jobs_yml']}")
    print(f"  wrappers ({len(result['wrappers'])}):")
    for p in result["wrappers"]:
        print(f"    {p}")