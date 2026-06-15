# assets.py
## Dagster asset definitions
### Calls pipeline.py functions

import pipeline
from dagster import asset
import pandas as pd


@asset
def setup():
    pipeline.run_setup()


@asset(deps=["setup"])
def bronze_request_api() -> list[dict]:
    return pipeline.run_bronze_request_api()


@asset(deps=["setup", "bronze_request_api"], group_name="bronze_layer")
def bronze_cases(bronze_request_api: list[dict]) -> pd.DataFrame:
    return pipeline.run_bronze_cases(bronze_request_api)


@asset(deps=["setup", "bronze_request_api"], group_name="bronze_layer")
def bronze_samples(bronze_request_api: list[dict]) -> pd.DataFrame:
    return pipeline.run_bronze_samples(bronze_request_api)


@asset(deps=["setup", "bronze_request_api"], group_name="bronze_layer")
def bronze_slides(bronze_request_api: list[dict]) -> pd.DataFrame:
    return pipeline.run_bronze_slides(bronze_request_api)


@asset(deps=["bronze_cases"], group_name="silver_layer")
def silver_cases() -> pd.DataFrame:
    return pipeline.run_silver_cases()


@asset(deps=["bronze_samples"], group_name="silver_layer")
def silver_samples() -> pd.DataFrame:
    return pipeline.run_silver_samples()


@asset(deps=["silver_cases", "silver_samples"], group_name="gold_layer")
def gold_mastertable() -> pd.DataFrame:
    return pipeline.run_gold_mastertable()