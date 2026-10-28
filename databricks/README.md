# ETL-CMS (OHDSI SynPUF) — End-to-End Run on Databricks

This guide takes the ETL-CMS pipeline from the Orion Launchpad intake form to tables in Unity Catalog. It is a test run, to make sure the whole flow works end to end:

```
intake form  →  orion.json  →  compile  →  databricks bundle  →  deploy  →  run on Databricks
```

The pipeline that comes out of it:

| Task | Layer | What it does |
|---|---|---|
| `orion_preflight` | — | Checks and creates the catalog, schema, volume and every folder (`omop_tables`, `control`, `bronze`, `silver`) |
| `bronze_table_setup_create_cdmv5_tables_sql` | bronze | Creates the empty OMOP CDM v5 tables |
| `bronze_get_data_get_synpuf_files_py` | bronze | Downloads CMS SynPUF sample 1 into `bronze/` |
| `silver_etl_cms_synpuf_etl_cdm_v5_py` | silver | Converts SynPUF to OMOP CSVs in `silver/` |
| `gold_load_to_tables_load_cdmv5_synpuf_sql` | gold | Loads the `silver/` CSVs into the OMOP tables |

## What you've been given

Everything this run needs is already in the repo. You don't download anything else:

| What | Where | Used in |
|---|---|---|
| The ETL-CMS source code, zipped | `tests/test_data/src.zip` | Step 1 (upload to the intake) |
| The OMOP vocabulary files `CONCEPT.csv` and `CONCEPT_RELATIONSHIP.csv` | `tests/test_data/omop_tables/` | Step 5b (upload to Databricks) |
| Where the intake config goes | `tests/test_data/sample_OrionConfig.json` | Steps 2–3a |

The bundle folder `databricks/` is not in the repo. Step 3 creates it: the compiler writes the bundle files, then you copy the code it needs into it.

---

## 0. Before you start

You need:

- **Python 3.11+ and the repo's virtual environment.** From the repo root:
  ```
  python -m venv .venv
  .venv\Scripts\activate
  pip install -r requirements.txt
  ```
- **The Databricks CLI** (v0.205 or newer). Check with `databricks --version`. If it's missing, install it with:
  ```
  winget install Databricks.DatabricksCLI
  ```
- **A login to the workspace:**
  ```
  databricks auth login --host https://<your-workspace>.cloud.databricks.com
  ```
  Then run `databricks auth profiles`. There should be exactly one profile for this host, showing `Valid: YES`. If an old `DEFAULT` profile shows `NO` for the same host, delete its `[DEFAULT]` block from `%USERPROFILE%\.databrickscfg`. Otherwise deploys fail with `403 Invalid access token`.
- **The files in `tests/test_data/`** listed under *What you've been given*: `src.zip` and the `omop_tables/` folder with `CONCEPT.csv` and `CONCEPT_RELATIONSHIP.csv`. Check they're there before you start.

All commands below run from the **repo root** (`dscs-templates/`) unless a step says otherwise.

---

## 1. Fill in the intake form

Start the intake:

```
streamlit run orion_intake_app/pages/minimal.py
```

Fill it in exactly as below. The goal is to produce the `orion.json` shown in the Appendix.

### Project name
- **Project name:** `etl_cms_ohdsi_test`

### 1. Source files
- Upload `tests/test_data/src.zip`.
- The scripts keep their paths from the zip, e.g. `src/CMS SynPUF ETL/scripts/get_synpuf_files.py`.

### 2. Languages
| Language | Version |
|---|---|
| Python | 3.9 |
| SQL | Spark SQL |

### 3. Environment
- **Platform:** `databricks`
- **Orchestrator:** `databricks_jobs`
- **Workspace URL:** your own workspace URL, e.g. `https://<your-workspace>.cloud.databricks.com` (copy it from your browser's address bar when you're logged in to Databricks; no trailing `/`)

### 4. Unity Catalog configuration
- **Catalog:** `etl_cms_test`
- **Schema:** `ohdsi_cdm_test`
- **Volume:** `ohdsi_volume_test`

**Volumes and folders.** Click **+ Add folder** twice:

| Volume | Subfolder |
|---|---|
| `ohdsi_volume_test` | `omop_tables` |
| `ohdsi_volume_test` | `control` |

> The OMOP vocabulary goes in `omop_tables` in step 5.

**Gold table definitions.** Choose **Yes**, then select `src/CMS SynPUF ETL/SQL/create_CDMv5_tables.sql`. This adds a locked **table setup** card:
- **Name:** `table_setup`
- **Layer type:** `bronze`

### 5. Medallion layers

Set up three layers, in this order. Rename or add layers as needed. For each parameter row, pick a folder variable from the dropdown, or choose **Custom value…** to type a value.

#### Layer 1: `get_data`
- **Layer name:** `get_data`; **Layer type:** `bronze`
- **Inputs:** none
- **Destination:** Volume folder. **Output folder:** create a new folder named `bronze`
- **Script to run:** `src/CMS SynPUF ETL/scripts/get_synpuf_files.py`
- **Parameters** (leave **Name** empty on both rows, so they are passed as positional arguments):

  | # | Name | Value |
  |---|---|---|
  | 1 | *(empty)* | `bronze_subfolder_path` (output folder) |
  | 2 | *(empty)* | Custom: `1` (sample number) |

  > The order matters. The script reads the output folder first, then the sample number.

#### Layer 2: `etl`
- **Layer name:** `etl`; **Layer type:** `silver`
- **Inputs:** Upstream layer → `get_data`
- **Destination:** Volume folder. **Output folder:** create a new folder named `silver`
- **Script to run:** `src/CMS SynPUF ETL/python_etl/CMS_SynPuf_ETL_CDM_v5.py`
- **Parameters:**

  | # | Name | Value |
  |---|---|---|
  | 1 | *(empty)* | Custom: `1` (sample number) |
  | 2 | `BASE_SYNPUF_INPUT_DIRECTORY` | `bronze_subfolder_path` |
  | 3 | `BASE_OUTPUT_DIRECTORY` | `silver_subfolder_path` |
  | 4 | `BASE_ETL_CONTROL_DIRECTORY` | `control_subfolder_path` |
  | 5 | `BASE_OMOP_INPUT_DIRECTORY` | `omop_tables_subfolder_path` |
  | 6 | `SYNPUF_DIR_FORMAT` | Custom: `DE_{0}` |

#### Layer 3: `load_to_tables`
- **Layer name:** `load_to_tables`; **Layer type:** `gold`
- **Inputs:** Upstream layer → `etl`. The table setup stage is added automatically, so it shows **Runs after: `table_setup`**.
- **Destination:** Unity Catalog tables. **Tables:** select all (required by the form; not used by the run yet)
- **Script to run:** `src/CMS SynPUF ETL/SQL/load_CDMv5_synpuf.sql`
- **Parameters:**

  | # | Name | Value |
  |---|---|---|
  | 1 | `data_dir` | `silver_subfolder_path` |

  > `data_dir` must be **lowercase**. It tells the SQL translator which folder the `\COPY` lines load from.

---

## 2. Save the config

Scroll to **orion.json preview** and copy the whole JSON. Paste it into:

```
tests\test_data\sample_OrionConfig.json
```

Replace whatever was there before. Compare it with the Appendix: the stages, parameters and folders should match.

---

## 3. Build the bundle

### 3a. Compile

From the repo root:

```
python -m utilities.compiler tests\test_data\sample_OrionConfig.json databricks
```

This does three things:
1. Validates the spec. If something is wrong it stops with a list like `stages[2] (etl).entry_point.parameters: ...`. Fix it in the intake and repeat steps 1–3a.
2. Writes `databricks\databricks.yml`, `databricks\resources\databricks_jobs.yml` and the task wrappers in `databricks\utilities\wrappers\`.
3. Validates the generated bundle.

Warnings in the output are fine. Only errors stop the compile.

### 3b. Copy the code into the bundle

The tasks run your scripts and Orion's checks on Databricks, so the bundle needs its own copy of them. From the repo root:

**Windows (PowerShell):**
```
robocopy src databricks\src /E /IS /IT /XD __pycache__
robocopy utilities databricks\utilities __init__.py logger.py sql_read.py sql_translate.py sql_execute.py emitter_helpers.py /IS /IT
robocopy validation databricks\validation __init__.py preflight_validator.py input_validator.py output_validator.py spec_validator.py /IS /IT
```

**Mac / Linux:**
```
mkdir -p databricks/utilities databricks/validation
cp -R src databricks/
cp utilities/{__init__,logger,sql_read,sql_translate,sql_execute,emitter_helpers}.py databricks/utilities/
cp validation/{preflight_validator,input_validator,output_validator,spec_validator}.py databricks/validation/
```

What gets copied, and why:

| From | To | Why |
|---|---|---|
| `src/` | `databricks/src/` | The ETL scripts and SQL the tasks run |
| `utilities/`: `logger`, `sql_read`, `sql_translate`, `sql_execute`, `emitter_helpers` | `databricks/utilities/` | Used by the task wrappers (SQL translation and logging) |
| `validation/`: `preflight_validator`, `input_validator`, `output_validator`, `spec_validator` | `databricks/validation/` | The checks that run inside each task |

The compiler, emitters and `generate_wrapper.py` are only used on your machine, so they aren't copied. Don't copy `utilities/wrappers/` either; step 3a generates it.

> Do this every time you change anything in `src/`, `utilities/` or `validation/`, then deploy again. The robocopy summary should show the changed files under **Copied**. If every count is 0, check you ran it from the repo root.

At the end, `databricks/` should contain `databricks.yml`, `resources/`, `src/`, `utilities/` (with `wrappers/`) and `validation/`.

---

## 4. Validate and deploy the bundle

```
cd databricks
databricks bundle validate -t dev
databricks bundle deploy -t dev
```

- `validate` should end with `Validation OK!`.
- `deploy` uploads the bundle to `/Workspace/Users/<you>/.bundle/etl_cms_ohdsi_test/dev/` and creates the job.

If `deploy` fails with `403 Invalid access token`, see the auth note in step 0.

---

## 5. Run on Databricks

### Find the job
1. Open your Databricks workspace.
2. In the left sidebar, click **Jobs & Pipelines**.
3. Open **`[dev <your name>] etl_cms_ohdsi_test`**. The `[dev …]` prefix is added because it was deployed with `-t dev`.
4. The **Tasks** tab shows the graph: `orion_preflight` → table setup and `get_data` → `etl` → `load_to_tables`.

### 5a. Run preflight first
Preflight creates the catalog, schema, volume and every folder the pipeline uses, so the vocabulary has somewhere to go. From the `databricks` folder:

```
databricks bundle run etl_cms_ohdsi_test --only orion_preflight
```

When it finishes, its log should show the catalog `etl_cms_test`, the schema `ohdsi_cdm_test`, the volume `ohdsi_volume_test` and the folders `omop_tables`, `control`, `bronze` and `silver` as found or created.

### 5b. Upload the OMOP vocabulary
1. In the left sidebar, click **Catalog**, then `etl_cms_test` → `ohdsi_cdm_test` → **Volumes** → `ohdsi_volume_test`.
2. Open the `omop_tables` folder (preflight created it).
3. Click **Upload to this volume** and upload `CONCEPT.csv` and `CONCEPT_RELATIONSHIP.csv` from `tests/test_data/omop_tables/` on your machine.

The final path should be `/Volumes/etl_cms_test/ohdsi_cdm_test/ohdsi_volume_test/omop_tables/CONCEPT.csv`.

### 5c. Run the rest
Either:
- **UI:** on the job page click **Run now**. Preflight runs again, which is harmless.
- **CLI** (from `databricks/`):
  ```
  databricks bundle run etl_cms_ohdsi_test
  ```

Open the run to watch each task. Click a task to see its log. Expect `get_data` and `etl` to take several minutes each.

### 5d. Check the results
- **Volume:** `bronze/` holds the SynPUF sample 1 files, and `silver/` holds `person_1.csv`, `visit_occurrence_1.csv` and so on.
- **Tables:** in a SQL editor:
  ```sql
  SELECT COUNT(*) FROM etl_cms_test.ohdsi_cdm_test.person;
  ```
- **The `load_to_tables` log:** one `[n/19] OK: COPY INTO …` line per table, ending with `summary: 19 succeeded, 0 failed`.

---

## Troubleshooting

| Message | Meaning / fix |
|---|---|
| `Orion check failed before running the script: … not found` / `is empty` | An input folder is missing or empty. Check the task it names ran successfully. For `omop_tables`, upload the vocabulary (5b). |
| `N new file(s) have the same name …  Nothing was overwritten` | The output folder already has files from an earlier run. Delete them in the volume, or use a new folder, then rerun. |
| `loads a file with \COPY: add a parameter named data_dir …` | The gold layer is missing `data_dir` (lowercase). Fix it in the intake and recompile. |
| `[x/19] FAILED: … MEASUREMENT …` | `load_CDMv5_synpuf.sql` loads into `MEASUREMENT`, but the table is `measurement_occurrence`. Change that line to `\COPY MEASUREMENT_OCCURRENCE …`. |
| `403 Invalid access token` on deploy | Stale `[DEFAULT]` profile. See step 0. |
| A fix you made doesn't show up on Databricks (old behaviour, old log messages) | The bundle has an old copy. Repeat step 3b, then deploy again. |
| `ModuleNotFoundError: No module named 'utilities'` or `'validation'` | A file is missing from the bundle. Repeat step 3b. |
| Want to start completely clean | In a SQL editor: `DROP CATALOG IF EXISTS etl_cms_test CASCADE;` (deletes everything in it), then go back to 5a. |

---

## Appendix: expected `orion.json`

`"generated"` will be your date. Everything else should match:

```json
{
  "apiVersion": "orion/v1",
  "project": "etl_cms_ohdsi_test",
  "platform": "databricks",
  "runtime": {
    "languages": [
      { "language": "Python", "version": "3.9" },
      { "language": "SQL", "version": "Spark SQL" }
    ],
    "orchestrator": "databricks_jobs",
    "workspace_url": "https://<your-workspace>.cloud.databricks.com"
  },
  "unity_catalog": {
    "catalog": "etl_cms_test",
    "schema": "ohdsi_cdm_test",
    "volume": "ohdsi_volume_test",
    "ddl_files": ["src/CMS SynPUF ETL/SQL/create_CDMv5_tables.sql"],
    "gold_tables": ["concept", "vocabulary", "domain", "...", "condition_era"],
    "folders": [
      { "volume": "ohdsi_volume_test", "subfolder": "omop_tables" },
      { "volume": "ohdsi_volume_test", "subfolder": "control" }
    ]
  },
  "stages": [
    {
      "name": "table_setup",
      "layer": "bronze",
      "sources": [],
      "entry_point": {
        "file": "create_CDMv5_tables.sql",
        "path": "src/CMS SynPUF ETL/SQL/create_CDMv5_tables.sql",
        "parameters": []
      },
      "destination": { "type": "tables", "catalog": "etl_cms_test", "schema": "ohdsi_cdm_test" }
    },
    {
      "name": "get_data",
      "layer": "bronze",
      "sources": [],
      "entry_point": {
        "file": "get_synpuf_files.py",
        "path": "src/CMS SynPUF ETL/scripts/get_synpuf_files.py",
        "parameters": ["${var.bronze_subfolder_path}", "1"]
      },
      "destination": { "type": "volume", "subfolder_name": "bronze" }
    },
    {
      "name": "etl",
      "layer": "silver",
      "sources": [{ "data_upload_type": "auto", "from": "get_data" }],
      "entry_point": {
        "file": "CMS_SynPuf_ETL_CDM_v5.py",
        "path": "src/CMS SynPUF ETL/python_etl/CMS_SynPuf_ETL_CDM_v5.py",
        "parameters": [
          "1",
          "BASE_SYNPUF_INPUT_DIRECTORY=${var.bronze_subfolder_path}",
          "BASE_OUTPUT_DIRECTORY=${var.silver_subfolder_path}",
          "BASE_ETL_CONTROL_DIRECTORY=${var.control_subfolder_path}",
          "BASE_OMOP_INPUT_DIRECTORY=${var.omop_tables_subfolder_path}",
          "SYNPUF_DIR_FORMAT=DE_{0}"
        ]
      },
      "destination": { "type": "volume", "subfolder_name": "silver" }
    },
    {
      "name": "load_to_tables",
      "layer": "gold",
      "sources": [
        { "data_upload_type": "auto", "from": "etl" },
        { "data_upload_type": "auto", "from": "table_setup" }
      ],
      "entry_point": {
        "file": "load_CDMv5_synpuf.sql",
        "path": "src/CMS SynPUF ETL/SQL/load_CDMv5_synpuf.sql",
        "parameters": ["data_dir=${var.silver_subfolder_path}"]
      },
      "destination": {
        "type": "tables",
        "catalog": "etl_cms_test",
        "schema": "ohdsi_cdm_test",
        "tables": ["concept", "vocabulary", "...", "condition_era"]
      }
    }
  ],
  "generated": "2026-10-28"
}
```