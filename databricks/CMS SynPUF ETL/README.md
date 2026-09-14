# Databricks Bundle Template for Legacy Python ETLs

A reference template for wrapping an existing GitHub-hosted Python ETL as a production-ready Databricks Asset Bundle. Uses the OHDSI ETL-CMS pipeline as a worked example, but the patterns apply to any single-machine Python ETL that reads/writes CSVs.

If you have a working Python ETL sitting on GitHub and want to run it on Databricks with proper orchestration, testing, and CI/CD, this template shows one way to structure it.


## Template structure

```
your-project/
├── databricks/                       # Bundle configuration
│   ├── databricks.yml                # Workspace, catalog, schema, Volume paths
│   └── resources/
│       └── job.yml                   # Pipeline task definitions
├── scripts/                          # Thin task wrappers (one per pipeline task)
├── utils/                            # Reusable helpers
│   ├── sql_translation.py            # Dialect translation (Postgres → Databricks SQL)
│   ├── execute_sql_file.py           # SQL execution against Spark
│   └── validate_output_schema.py     # Table schema introspection
├── SQL/                              # Source SQL files (Postgres dialect)
├── python_etl/                       # Your legacy Python ETL code
├── requirements.txt                  # Runtime dependencies
└── README.md
```

The idea: think of your pipeline as sequential stages, each in its own folder. Keep your legacy code isolated in one stage. Add Databricks-specific glue elsewhere.

## Adapting this template to your project

### 1. Structure your repository as pipeline stages

Organize your project by pipeline stage, not by file type. Each folder represents a step in your data flow.

### 2. Configure the bundle

Edit `databricks/databricks.yml` for your workspace:

```yaml
bundle:
  name: your_project

variables:
  catalog:
    description: Unity Catalog for your data
  schema:
    description: Schema within the catalog
  # ... your Volume paths

targets:
  dev:
    workspace:
      host: https://<your-workspace>.cloud.databricks.com
    variables:
      catalog: your_catalog
      schema: your_schema
      # ...
```

### 3. Define your pipeline tasks

In `databricks/resources/job.yml`, replace the OHDSI-specific tasks with tasks that fit your pipeline.

The pattern:

- Each task is a thin script in `scripts/`
- Task passes catalog, schema, and any paths as parameters
- Tasks depend on each other via `depends_on:`
- All tasks use the `default_env` serverless environment

Example task pattern:

```yaml
- task_key: your_task
  description: What this task does
  depends_on:
    - task_key: prior_task
  environment_key: default_env
  spark_python_task:
    python_file: ../../scripts/your_task.py
    parameters:
      - "${var.catalog}"
      - "${var.schema}"
      # ... other params
```

### 4. Write the task wrappers

Each script in `scripts/` is a thin wrapper. It:

- Parses command-line arguments
- Calls into your ETL code or the utilities
- Exits with 0 on success or 1 on failure

See the examples in `scripts/` for the pattern.

### 5. Handle configuration

If your ETL needs configuration that can't come via task parameters (e.g., `os.environ`), place a `.env` file on a Volume and load it in your ETL code:

```python
from dotenv import load_dotenv
load_dotenv("/Volumes/<catalog>/<schema>/config/.env")
```

This works around the serverless env var limitation.

### 6. Deploy

```bash
cd databricks
databricks bundle deploy --target dev
```

Then trigger the job from the Databricks UI or via CLI.

## Key patterns demonstrated

### Postgres → Databricks SQL translation

Legacy projects often have Postgres DDL that needs to run on Databricks. See `utils/sql_translation.py`:

- Uses [sqlglot](https://github.com/tobymao/sqlglot) to parse and transpile
- Handles dialect-specific gaps (standalone NULL constraints, psql client prefixes like `\COPY`)
- Blacklists commands with no Databricks equivalent (`\cd`, etc.)

Use this pattern when your project has SQL files you don't want to rewrite by hand.

### CSV → typed table loading

Legacy Python ETLs write CSVs. Loading them into Databricks tables cleanly requires knowing the target types. See `scripts/load_omop_output.py` and `utils/validate_output_schema.py`:

- Discovers CSVs by directory listing (no hardcoded file list)
- Discovers tables by `SHOW TABLES` (no hardcoded table list)
- Retrieves schemas from existing tables (no hardcoded types)
- Casts CSV columns to target types before writing

Use this pattern when your ETL produces CSVs and you want them loaded into typed tables.

### /tmp for filesystem-heavy workloads

Databricks Volumes are cloud object storage under the hood. They don't support:

- Long-held file handles
- Append-mode writes over time
- Frequent flushes on open files

If your ETL uses these patterns, route it through `/tmp` (local disk) and copy to the Volume when done. See the copy step at the end of `python_etl/CMS_SynPuf_ETL_CDM_v5.py`.

Use this pattern when your ETL keeps many files open, writes incrementally, or does heavy filesystem I/O.

### Volume-based configuration

Databricks serverless doesn't allow setting OS environment variables via YAML. The `.env` file lives on a Volume; the ETL loads it via absolute path with `python-dotenv`.

Use this pattern when your ETL reads `os.environ` for configuration and you can't rewrite it to accept command-line arguments.

## The worked example: OHDSI ETL-CMS

The `python_etl/` folder contains the [OHDSI ETL-CMS](https://github.com/OHDSI/ETL-CMS) pipeline, ported to Python 3 and adapted to run on Databricks using this template. The `SQL/` folder contains OHDSI's original Postgres DDL.

The pipeline transforms CMS SynPUF Medicare claims data into OMOP Common Data Model v5 format via four tasks:

1. **download_synpuf_raw** — downloads SynPUF sample data
2. **create_omop_tables** — creates OMOP CDM tables from translated Postgres DDL
3. **run_python_etl** — runs the legacy Python ETL to transform SynPUF → OMOP CSVs
4. **load_omop_output** — loads CSVs into typed OMOP tables

If you want to run this specific pipeline, see the [OHDSI-specific setup section](#running-the-example-ohdsi-pipeline) below.

## Prerequisites

For using this template with any project:

- Databricks workspace (serverless compute is fine; job clusters not required)
- Unity Catalog (for typed tables)
- A Volume (for shared storage between tasks)
- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) installed and authenticated

For the OHDSI example specifically:

- OMOP vocabulary files from [Athena](https://athena.ohdsi.org/) uploaded to a Volume
- ~10 GB of Volume storage per sample
- Serverless environment with Python 3.12 (default)

## Attribution

- [OHDSI ETL-CMS](https://github.com/OHDSI/ETL-CMS) — the worked example pipeline
- [sqlglot](https://github.com/tobymao/sqlglot) — SQL dialect translation
- Databricks Asset Bundles — orchestration framework

## Running the example OHDSI pipeline

If you want to actually run the OHDSI ETL-CMS pipeline (rather than adapt this template for your own project), follow the setup steps in the sections above and use the following configuration:

*[Add specific OHDSI setup instructions here — Volume paths, .env file contents, vocabulary download instructions, etc.]*

