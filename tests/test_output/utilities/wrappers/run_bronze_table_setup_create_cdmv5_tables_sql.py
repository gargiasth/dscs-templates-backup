"""Wrapper for stage: table_setup — entry-point: create_CDMv5_tables.sql"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))          # so `utilities` imports on Databricks

from utilities.sql_read import read_sql_file
from utilities.sql_translate import translate
from utilities.sql_execute import execute_statements

_SQL_PATH = _REPO_ROOT / "src/CMS SynPUF ETL/SQL/create_CDMv5_tables.sql"

# ── Orion checks: ORION_INPUT / ORION_OUTPUT parameters are for the wrapper, not the script ──
orion_inputs, orion_output, rest = [], None, []
for a in sys.argv[1:]:
    if a.startswith("ORION_INPUT="):
        path, _, who = a[len("ORION_INPUT="):].partition("|")
        orion_inputs.append((path, who or "an earlier step"))
    elif a.startswith("ORION_OUTPUT="):
        orion_output = a[len("ORION_OUTPUT="):]
    else:
        rest.append(a)

if orion_inputs or orion_output:
    sys.path.insert(0, str(_REPO_ROOT))      # so `validation` and `utilities` import on Databricks
    from validation.input_validator import check_inputs, InputValidationError
    from validation.output_validator import prepare_output, finish_output, OutputValidationError
    try:
        if orion_inputs:
            check_inputs(orion_inputs, platform="databricks")
        if orion_output:
            # The script writes to a holding folder; Orion moves the files in afterwards,
            # refusing any that would overwrite a file already in the output folder.
            orion_staging = str(prepare_output(orion_output, platform="databricks"))
            import re as _re
            _out = _re.compile(_re.escape(orion_output.rstrip("/")) + r"(?=/|$)")
            rest = [_out.sub(lambda _m: orion_staging, a) for a in rest]
    except (InputValidationError, OutputValidationError) as e:
        sys.exit(f"Orion check failed before running the script:\n{e}")

if len(rest) < 2:
    sys.exit("usage: <wrapper> <catalog> <schema>")
catalog = rest[0]
schema  = rest[1]

results    = translate(read_sql_file(_SQL_PATH), read="postgres", dialect="databricks")
statements = [item["sql"] for item in results if not item["unsupported_reason"]]

summary = execute_statements(statements, catalog=catalog, schema=schema)
if summary["failed"]:
    sys.exit(1)

if orion_output:
    try:
        finish_output(orion_output, orion_staging)
    except OutputValidationError as e:
        sys.exit(f"Orion check failed after running the script:\n{e}")
