# Utilities

The utilities currently only consist of Databricks YML config emitter that turn an Orion intake spec into a Databricks Asset Bundle.

## Files

- `emitter_helpers.py` — shared helpers
- `databricks_yml_emitter.py` — builds `databricks.yml`
- `databricks_jobs_emitter.py` — builds `resources/databricks_jobs.yml`
- `logger.py` — logging setup
- `test_data/` — sample Orion spec
- `test_output/` — emitter output lands here

## Usage

From the repo root:

```bash
python -m utilities.databricks_yml_emitter   utilities/test_data/sample_OrionConfig.json
python -m utilities.databricks_jobs_emitter  utilities/test_data/sample_OrionConfig.json
```

Writes:

- `utilities/test_output/databricks.yml`
- `utilities/test_output/resources/databricks_jobs.yml`

Or from Python:

```python
from utilities.databricks_yml_emitter  import build_databricks_yml
from utilities.databricks_jobs_emitter import build_jobs_yml

yml  = build_databricks_yml(spec)
jobs = build_jobs_yml(spec)
```

## Tests

From the repo root:

```bash
pytest tests/
```