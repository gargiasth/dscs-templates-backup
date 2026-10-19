# Utilities

Compiles an Orion spec (`orion.json`) into a Databricks Asset Bundle.


## Pipeline

```
orion.json
    │
    └──▶ compiler.py
            │
            ├──▶ generate_wrapper.py          → utilities/wrappers/
            ├──▶ databricks_yml_emitter.py    → databricks.yml
            └──▶ databricks_jobs_emitter.py   → resources/databricks_jobs.yml
```

`compiler.py` runs the three steps in order. Wrappers are written first because the jobs YAML references them by path.


## Files

### compiler.py

The entry point. Reads `orion.json` from disk, runs the three steps in order, and returns the paths of every file it wrote. All path and filename conventions (where wrappers go, what the YAML files are named, what prefix the wrapper files use) are defined as constants at the top of this file and passed into the other modules as arguments.

Public API: `compile_bundle(spec_path, output_dir) -> dict`

### generate_wrapper.py

For every stage in the spec that has an `entry_point`, writes one wrapper Python file into `utilities/wrappers/`. The wrapper is what Databricks tasks actually execute. There are two wrapper templates, picked by the entry point's file extension:

* `.py` entry point: the wrapper uses `subprocess.run` to call the user's script, forwarding every CLI argument the task passes.
* `.sql` entry point: the wrapper reads the SQL file, translates it with `sql_translate`, and runs each statement via `spark.sql()`.

Wrapper filenames follow the format `run_<task_key>.py` so they match the task keys the jobs emitter produces.

Public API: `produce_wrapper(stage, wrapper_depth)` and `write_all_wrappers(spec, output_dir, wrapper_prefix, wrapper_depth)`

### databricks_yml_emitter.py

Builds the top-level `databricks.yml` string. The content includes:

* `bundle.name`: the project name from the spec
* `variables`: declared from the Unity Catalog block (catalog, schema, volume) and every source or destination subfolder path across all stages
* `include`: the glob pattern that pulls in `resources/*.yml`
* `targets`: a `dev` target with the workspace URL, if the spec provides one

Public API: `build_databricks_yml(spec, resources_dir) -> str`

### databricks_jobs_emitter.py

Builds the jobs YAML string that goes under `resources/`. Walks every stage and emits one task per download script (from `custom_script` sources) and one task per transform script (from `stage.scripts`). Dependencies are derived from `auto` sources: a stage with `data_upload_type: auto` from a prior stage becomes a downstream task that `depends_on` the upstream one. Each task's `python_file` points at the generated wrapper, not the user's raw script.

Public API: `build_jobs_yml(spec, wrapper_dir, wrapper_prefix) -> str`

### sql_read.py

Pure Python, no Databricks dependency. Three functions:

* `read_sql_file(path)`: reads a `.sql` file as UTF-8 text, stripping any byte order mark Windows tools tend to add.
* `parse_statements(sql, source_dialect)`: parses the SQL into a list of `sqlglot` AST nodes. Uses `ErrorLevel.IGNORE` so malformed statements get skipped rather than raising.
* `extract_table_names(sql, source_dialect)`: pulls bare table names (schema and catalog qualifiers stripped) from every CREATE TABLE statement.

### sql_translate.py

Translates SQL from one dialect to another using per-dialect translator functions registered in a `_TRANSLATORS` dict.

Public API: `translate(sql, read, dialect) -> list[dict]`

Returns one dict per statement with the translated SQL and an `unsupported_reason` field. The caller decides what to do with unsupported statements (skip, log, attempt anyway) rather than this function silently dropping them.

Current targets:

* `databricks`: strips Postgres `col TYPE NULL` constraints (Databricks rejects them), appends `USING DELTA` to CREATE TABLE statements, flags CREATE SEQUENCE and `nextval()` as unsupported.
* `snowflake`: basic sqlglot translation with no custom pre or postprocessing yet.

Adding a new dialect means writing one `_translate_statement_for_<name>(ast)` function and registering it in `_TRANSLATORS`.

### emitter_helpers.py

Shared helpers used by both emitters. Does not configure logging itself, the importing module is expected to call `setup_logging()`.

* `_var_safe(text)`: lowercases a string and replaces non-alphanumeric runs with underscores. Safe for use as a bundle variable name segment.
* `_var_ref(name)`: formats a name as the bundle variable reference `${var.name}`.
* `_volume_path(uc, subfolder)`: composes a Unity Catalog volume path like `/Volumes/<catalog>/<schema>/<volume>/<subfolder>`.
* `_task_key(layer, stage_name, identifier)`: builds the task key convention `<layer>_<stage>_<identifier>`.
* `_collect_variables(spec)`: walks the spec and returns the flat variables dict the yml emitter writes out and the jobs emitter uses to decide whether a parameter should be a `${var.X}` reference or a literal path.

### logger.py

Centralized logging setup. Every module calls `setup_logging()` on import so logs have a consistent format across the pipeline.

### test_data/

Sample Orion specs for local testing. Includes `sample_OrionConfig.json`.

### test_output/

Default output directory for compiled bundles. Not checked into git.


## Wrappers

Databricks tasks run one Python file. The wrapper is that file.

* `.py` entry point: wrapper subprocesses the user's script.
* `.sql` entry point: wrapper reads, translates, and executes via `spark.sql()`.

The wrapper filename equals `run_<task_key>.py`, so the jobs YAML and the wrapper files always match.


## Usage

From the repo root:

```bash
python -m utilities.compiler
```

With explicit paths:

```bash
python -m utilities.compiler path/to/orion.json path/to/output_dir
```

From Python:

```python
from utilities.compiler import compile_bundle

result = compile_bundle("orion.json", "output_dir")
```

Output tree:

```
<output_dir>/
├── databricks.yml
├── resources/
│   └── databricks_jobs.yml
└── utilities/
    └── wrappers/
        └── run_<task_key>.py
```


## Path conventions

All path and filename conventions live at the top of `compiler.py`:

```python
DATABRICKS_YML_NAME = "databricks.yml"
RESOURCES_DIR       = Path("resources")
JOBS_YML_NAME       = "databricks_jobs.yml"
WRAPPER_DIR         = Path("utilities") / "wrappers"
WRAPPER_PREFIX      = "run_"
```

The emitters and generator receive these as arguments. Change one constant and every output follows.