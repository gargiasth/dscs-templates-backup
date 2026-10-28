"""
Orion Launchpad — bundle compiler.

Takes an orion.json spec, runs the generators and emitters in order,
produces a working Databricks bundle in the output directory.

The compiler is the entry point, each step
(wrapper generator, YAML emitters) is a stage that happens inside it.
Users run one command and get a complete bundle.

Order matters:
    1. Wrappers: the jobs YAML references them, so they must
       exist on disk before the YAML lands.
    2. databricks.yml: bundle metadata, no cross-references.
    3. jobs YAML: references wrappers by path.

Public entry point:
    compile_bundle(spec_path, output_dir) -> dict
    (if spec_path and output_dir are not specified, it will use a default)

CLI usage:
    python -m utilities.compiler [orion.json] [output_dir]
"""

import json
import logging
from pathlib import Path, PurePosixPath

from utilities.logger import setup_logging
from utilities.generate_wrapper import write_all_wrappers
from utilities.databricks_yml_emitter import build_databricks_yml
from utilities.databricks_jobs_emitter import build_jobs_yml
from validation.spec_validator import validate_spec, SpecValidationError
from validation.databricks_bundle_validator import validate_bundle, BundleValidationError

setup_logging()
log = logging.getLogger(__name__)


# ── Paths ────────────────────────────────────────────────────────────────────
# Inputs: defaults used when the caller doesn't pass spec_path / output_dir.
DEFAULT_SPEC_PATH  = Path("tests/test_data/sample_OrionConfig.json")
DEFAULT_OUTPUT_DIR = Path("databricks")

# Bundle layout: relative to output_dir.
DATABRICKS_YML_NAME = "databricks.yml"
RESOURCES_DIR       = Path("resources")
JOBS_YML_NAME       = "databricks_jobs.yml"
WRAPPER_DIR         = Path("utilities") / "wrappers"
WRAPPER_PREFIX      = "run_"


# ── Public API ───────────────────────────────────────────────────────────────

def compile_bundle(
    spec_path: str | Path = DEFAULT_SPEC_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> dict:
    """Compile an orion.json spec into a Databricks bundle at output_dir.

    Produces this tree:
        <output_dir>/
        ├── databricks.yml
        ├── resources/
        │   └── databricks_jobs.yml
        └── utilities/
            └── wrappers/
                ├── run_<task_key>.py
                └── ...

    Returns a dict of paths written:
        {
            "wrappers":       [Path, ...],
            "databricks_yml": Path,
            "jobs_yml":       Path,
        }
    """
    spec_path  = Path(spec_path)
    output_dir = Path(output_dir)

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    log.info("compiling %s → %s", spec_path, output_dir)

    # ── Step 0: validate the spec ──
    # Report every problem at once; write nothing if there are errors.
    # repo_root = the folder you run the compiler from; entry_point.path is relative to it.
    report = validate_spec(spec, repo_root=Path.cwd())   # logs each problem as it is found
    if report.errors:
        raise SpecValidationError(report.errors)

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: wrappers ──
    # The jobs YAML will reference these by path, so write them first.
    wrapper_paths = _emit_wrappers(spec, output_dir)

    # ── Step 2: databricks.yml ──
    # Bundle metadata — name, targets, variables. No cross-refs.
    databricks_yml_path = _emit_databricks_yml(spec, output_dir)

    # ── Step 3: jobs YAML ──
    # Task definitions. Each task points at a wrapper from step 1.
    jobs_yml_path = _emit_jobs_yml(spec, output_dir)

    # ── Step 4: check the files we just wrote agree with each other ──
    # A failure here is a compiler bug, not a spec problem.
    bundle_report = validate_bundle(output_dir, RESOURCES_DIR / JOBS_YML_NAME, WRAPPER_DIR)
    if bundle_report.errors:
        raise BundleValidationError(bundle_report.errors)

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
    wrapper_dir = output_dir / WRAPPER_DIR
    written = write_all_wrappers(
        spec,
        wrapper_dir,
        wrapper_prefix=WRAPPER_PREFIX,
        wrapper_depth=len(WRAPPER_DIR.parts),
    )
    log.info("step 1: wrote %d wrapper(s) → %s", len(written), wrapper_dir)
    return written


def _emit_databricks_yml(spec: dict, output_dir: Path) -> Path:
    yml_content = build_databricks_yml(spec, resources_dir=RESOURCES_DIR.as_posix())
    yml_path = output_dir / DATABRICKS_YML_NAME
    yml_path.write_text(yml_content, encoding="utf-8")
    log.info("step 2: wrote %s", yml_path)
    return yml_path


def _emit_jobs_yml(spec: dict, output_dir: Path) -> Path:
    # Wrapper dir as seen from the jobs YAML, e.g. ../utilities/wrappers
    wrapper_ref = PurePosixPath(*[".."] * len(RESOURCES_DIR.parts), *WRAPPER_DIR.parts).as_posix()
    # Job environment packages come from the repo root's requirements.txt
    jobs_content = build_jobs_yml(spec, wrapper_dir=wrapper_ref, wrapper_prefix=WRAPPER_PREFIX,
                                  requirements_path=Path.cwd() / "requirements.txt")
    jobs_path = output_dir / RESOURCES_DIR / JOBS_YML_NAME
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
        type=Path,
        default=DEFAULT_SPEC_PATH,
        help="Path to orion.json (default: %(default)s)",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Where to write the bundle (default: %(default)s)",
    )
    args = parser.parse_args()

    result = compile_bundle(args.spec_path, args.output_dir)

    print(f"\nCompiled bundle:")
    print(f"  databricks.yml:        {result['databricks_yml']}")
    print(f"  resources/jobs.yml:    {result['jobs_yml']}")
    print(f"  wrappers ({len(result['wrappers'])}):")
    for p in result["wrappers"]:
        print(f"    {p}")