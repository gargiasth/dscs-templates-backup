# Snowpark Container Services Template for Legacy Python ETLs

A reference template for wrapping an existing GitHub-hosted Python ETL as a production-ready pipeline on Snowpark Container Services (SPCS). Uses the OHDSI ETL-CMS pipeline as a worked example, but the patterns apply to any single-machine Python ETL that reads/writes CSVs — the same source code, ported to a second platform, using the same "isolate legacy code, add platform-specific glue elsewhere" principle as the companion Databricks template.

## Template structure

```
your-project/
├── docker/                           # Container build
│   ├── Dockerfile                    # Single image, generic ENTRYPOINT
│   └── requirements.txt              # Runtime dependencies
├── spcs/
│   ├── config/                       # Reference copies of job specs
│   ├── ingestion/                    # Raw data download → Bronze stage
│   ├── etl_snowflake/                # Runs the legacy ETL, loads to Gold
│   ├── setup/                        # One-time table/stage creation
│   └── utils_snowflake/              # Reusable helpers
│       ├── connection.py             # Dual-mode auth (local vs. in-container)
│       ├── sql_translation.py        # Dialect translation (Postgres → Snowflake)
│       ├── execute_sql_file.py       # SQL execution
│       ├── upload_to_stage.py        # Stream files to a stage
│       └── load_to_table.py          # COPY INTO, any file format
├── src/
│   ├── SQL/                          # Source SQL files (Postgres dialect)
│   ├── scripts/                      # Upstream data-fetching utilities
│   └── python_etl/                   # Your legacy Python ETL code
└── README.md
```

The idea: one Docker image, one generic `ENTRYPOINT`, and every pipeline step is just a different `command:` in its job spec pointing at the same image. Legacy code stays untouched in its own folder; every platform-specific decision lives in `spcs/`.

## Adapting this template to your project

### 1. Build one generic container image

The Dockerfile installs dependencies once, copies your code in, and sets `ENTRYPOINT ["python"]` — no script is baked in. Which script runs is decided per-job, not per-image:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY docker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY spcs/ /app/spcs/
COPY src/python_etl/ /app/src/python_etl/
ENTRYPOINT ["python"]
```

### 2. Handle authentication for both local and in-container runs

SPCS auto-provisions an OAuth token inside every running container; local runs need `.env` credentials instead. One function handles both, so nothing else in the codebase needs to know which environment it's in:

```python
def get_connection():
    token_path = "/snowflake/session/token"
    if os.path.exists(token_path):
        with open(token_path, "r") as f:
            token = f.read()
        return snowflake.connector.connect(
            host=os.environ["SNOWFLAKE_HOST"],
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            token=token,
            authenticator="oauth",
        )
    else:
        return snowflake.connector.connect(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            password=os.environ["SNOWFLAKE_PASSWORD"],
            warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
            role=os.environ["SNOWFLAKE_ROLE"],
        )
```
### 3. Deploy

```sql
CREATE IMAGE REPOSITORY IF NOT EXISTS <db>.<schema>.<repo_name>;
CREATE COMPUTE POOL IF NOT EXISTS <pool_name> MIN_NODES = 1 MAX_NODES = 1 INSTANCE_FAMILY = CPU_X64_S;
```

```bash
docker build -f docker/Dockerfile -t etl-cms-image .
docker tag etl-cms-image <registry_url>/etl-cms-image:latest
docker push <registry_url>/etl-cms-image:latest
```


### 4. Wrap each pipeline step in a parameterized stored procedure

Each job spec's `image:`, `env:`, and `command:` live inside a Python stored procedure, so a sample/run number becomes a real function argument instead of a hand-edited YAML file:

```sql
CREATE OR REPLACE PROCEDURE run_etl_job(sample_number NUMBER)
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.10'
HANDLER = 'run'
PACKAGES = ('snowflake-snowpark-python')
AS
$$
import time

def run(session, sample_number):
    spec = f"""
spec:
  containers:
    - name: run-etl
      image: <your_registry_url>/etl-cms-image:latest
      command: ["python", "/app/spcs/etl_snowflake/run_etl.py", "{sample_number}"]
      env:
        SNOWFLAKE_DATABASE: ETL_CMS
        ...
"""
    job_name = f"run_etl_job_{sample_number}_{int(time.time())}"
    escaped_spec = spec.replace("'", "''")
    sql = f"""
        EXECUTE JOB SERVICE
          IN COMPUTE POOL etl_cms_pool
          NAME = {job_name}
          ASYNC = TRUE
          FROM SPECIFICATION '{escaped_spec}'
    """
    session.sql(sql).collect()
    return f"Started {job_name}"
$$;
```

Call with `CALL run_etl_job(4);` — same shape for every pipeline stage.

`spcs/config/` holds template copies of each job's YAML spec — draft a new job's spec there first, as a plain, readable file, before manually embedding that same text into a `CREATE PROCEDURE` statement's Python string (as shown above). Snowflake has no way to load a spec directly from a file on disk into a procedure — the embedding is a manual, one-time copy. Because of that, these files are not read at runtime and can drift out of sync with what's actually deployed; treat them as a starting template and a human-readable reference, not a live source of truth. If you update a procedure's image tag or environment variables, update the matching file here too, or note in the file that it may be stale.


## Notes & Caveats

### `EXECUTE JOB SERVICE`, not `CREATE SERVICE`

`CREATE SERVICE` is for long-running services (a dashboard, an API); it restarts if it exits. `EXECUTE JOB SERVICE` runs once and exits, exactly matching a batch ETL step. Using the wrong one for a batch job leaves compute idling and billing indefinitely.

### 1. External access needs explicit opt-in, even inside a container

SPCS containers have no internet access by default — the same restriction stored procedures have. Any step reaching an external site (CMS.gov, in this project's case) needs a Network Rule + External Access Integration, referenced explicitly via `EXTERNAL_ACCESS_INTEGRATIONS = (...)` on the job itself.

### 2. Container memory limits are explicit and can be smaller than the node

Unlike a Databricks driver node (which gives a process access to close to the whole node's physical memory), an SPCS job spec requires declaring its own `resources.limits.memory` — a hard ceiling that can sit well below the node's actual capacity if under-provisioned. Getting this wrong causes a silent kill: no exception, no traceback, just the process stopping.

### 3. Mounted stages don't support append-mode or long-lived file handles

Confirmed directly from Snowflake's own SPCS docs. If your legacy ETL keeps files open and writes to them incrementally (as this one does, for `unmapped_code_log.txt` and cross-run state files), route those specific writes through the container's local `/tmp` during the run, then upload the finished files to a stage once every handle is closed — mirrors the identical fix needed for Databricks Volumes.

### 4. Unbuffered output for trustworthy logs

Python batches `stdout` when it isn't writing to a live terminal — exactly what happens inside a container. Logs can appear to "freeze" at an identical point on every run when the process is actually still working; the output is just sitting in an unflushed buffer. Set `PYTHONUNBUFFERED=1` in the subprocess environment for real-time, trustworthy logs.

### 5. Large-file sorts need to be disk-backed, not in-memory

A legacy script that loads an entire file into memory for sorting can work fine on a laptop (effectively unconstrained memory) and fail immediately in a memory-limited container. Shell out to the system's external sort utility instead of a language-native in-memory sort — bounded memory footprint regardless of file size.

## 6. The worked example: OHDSI ETL-CMS

The pipeline transforms CMS SynPUF Medicare claims data into OMOP Common Data Model v5 format via three stages, each a parameterized stored procedure:

1. **`sf_getdata_job`** — downloads SynPUF sample data, stages it fully in-memory
2. **`run_etl_job`** — runs the legacy Python ETL against staged data, uploads results
3. **`load_to_gold_job`** — loads the ETL's output CSVs into typed OMOP CDM tables via `COPY INTO`

## Prerequisites

- Snowflake account with SPCS enabled
- A database, schema, and dedicated compute pool (not shared with unrelated projects)
- Docker installed locally, for building and pushing images
- [OMOP vocabulary files](https://athena.ohdsi.org/) downloaded manually (Athena has no public API) and uploaded to a stage

## Attribution

- [OHDSI ETL-CMS](https://github.com/OHDSI/ETL-CMS) — the worked example pipeline
- [sqlglot](https://github.com/tobymao/sqlglot) — SQL dialect translation
- Snowpark Container Services — orchestration and compute