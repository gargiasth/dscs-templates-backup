"""
Try the input and output validators by hand, on your own machine.

Run from the repo root:
    python -m scripts.try_io_validators

It builds a throwaway folder (printed at the start), runs each scenario,
and prints PASS or the exact error the task would stop with. Nothing in
your repo or on Databricks is touched.
"""

import shutil
import tempfile
from pathlib import Path

from validation.input_validator import check_inputs, InputValidationError
from validation.output_validator import prepare_output, finish_output, OutputValidationError

ROOT = Path(tempfile.mkdtemp(prefix="orion_try_"))


def write(rel, text="id,name\n1,a\n"):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def scenario(title, fn):
    print(f"\n=== {title}")
    try:
        fn()
        print("PASS")
    except (InputValidationError, OutputValidationError) as e:
        print(f"STOPPED:\n{e}")


# ── Input scenarios ──────────────────────────────────────────────────────────

def good_input():
    write("synpuf_raw/DE_1/beneficiary.csv")
    write("vocab/CONCEPT.csv", "concept_id\tconcept_name\n1\tAspirin\n")     # tab-separated "csv"
    check_inputs([(ROOT / "synpuf_raw", "upstream task bronze_bronze_get_synpuf_files_py"),
                  (ROOT / "vocab", "manual upload")])

def missing_input():
    check_inputs([(ROOT / "not_there", "upstream task bronze_bronze_get_synpuf_files_py")])

def broken_csv():
    write("bad/a.csv", "id,ID,\n1,2\n3\n")       # duplicate header, empty header, short rows
    check_inputs([(ROOT / "bad", "manual upload")])


# ── Output scenarios ─────────────────────────────────────────────────────────

def fake_script(staging, files):
    """Stands in for your script: writes files into the folder it was given."""
    for name, text in files.items():
        p = Path(staging) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

def good_output():
    out = ROOT / "etl_output_1"
    write("etl_output_1/old_run.csv")                              # earlier files are fine
    staging = prepare_output(out)
    fake_script(staging, {"person.csv": "id\n1\n", "control/state.txt": "done"})
    moved = finish_output(out, staging)
    print("now in output folder:", sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()))
    print("moved in:", [p.name for p in moved])

def clashing_output():
    out = ROOT / "etl_output_2"
    write("etl_output_2/person.csv", "old\n1\n")
    staging = prepare_output(out)
    fake_script(staging, {"person.csv": "new\n2\n"})
    try:
        finish_output(out, staging)
    finally:
        print("old person.csv still says:", (out / "person.csv").read_text().splitlines()[0])

def empty_output():
    out = ROOT / "etl_output_3"
    staging = prepare_output(out)
    fake_script(staging, {})                                        # script wrote nothing
    finish_output(out, staging)


if __name__ == "__main__":
    print("working in", ROOT)
    scenario("Input: good folders (incl. tab-separated .csv)", good_input)
    scenario("Input: upstream folder missing", missing_input)
    scenario("Input: broken CSV", broken_csv)
    scenario("Output: earlier files kept, new files moved in", good_output)
    scenario("Output: same file name as an existing one", clashing_output)
    scenario("Output: script wrote nothing", empty_output)
    shutil.rmtree(ROOT, ignore_errors=True)
    print("\ncleaned up", ROOT)