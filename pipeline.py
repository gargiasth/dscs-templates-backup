# pipeline.py
## Core pipeline logic — orchestration tool agnostic
### Contains the full Bronze → Silver → Gold execution logic
### Called by assets.py but not dependent on Dagster or any orchestration tool
### To swap orchestration tools, replace assets.py only — this file is untouched

import pandas as pd

from config.database import ACTIVE_ENGINE, create_table
from config.schemas import (
    BRONZE_CASES_SCHEMA, BRONZE_SAMPLES_SCHEMA, BRONZE_SLIDES_SCHEMA,
    SILVER_CASES_SCHEMA, SILVER_SAMPLES_SCHEMA,
    GOLD_MASTERTABLE_SCHEMA, infer_schema
)
from ingestion.fetch import fetch_cases, fetch_default
from ingestion.extract import extract_cases, extract_samples, extract_slides, extract_default
from transforms.silver import transform_silver
from transforms.gold import join_tables
from utils.helpers import ensure_dirs, write_df_to_table
from validation.validate import validate, validate_row_count


def run_setup() -> None:
    ensure_dirs("data/")


# Initializing tables
def run_create_bronze_landing_table(hits: list[dict]) -> None:
    rows   = extract_default(hits)
    schema = infer_schema(rows[0])
    create_table("bronze_landing", schema)


def run_create_bronze_tables() -> None:
    create_table("bronze_cases",   BRONZE_CASES_SCHEMA)
    create_table("bronze_samples", BRONZE_SAMPLES_SCHEMA)
    create_table("bronze_slides",  BRONZE_SLIDES_SCHEMA)


def run_create_silver_tables() -> None:
    create_table("silver_cases",   SILVER_CASES_SCHEMA)
    create_table("silver_samples", SILVER_SAMPLES_SCHEMA)


def run_create_gold_tables() -> None:
    create_table("gold_mastertable", GOLD_MASTERTABLE_SCHEMA)


# Bronze landing — default GDC response
def run_bronze_landing() -> pd.DataFrame:
    hits = fetch_default()
    rows = extract_default(hits)
    df   = pd.DataFrame(rows)
    validate_row_count(df, min_rows=1, layer="bronze_landing")
    write_df_to_table(df, "bronze_landing", ACTIVE_ENGINE)
    print(f"bronze_landing — {len(df)} rows, {len(df.columns)} columns")
    return df


# Bronze layer
def run_bronze_request_api() -> list[dict]:
    hits = fetch_cases()
    print(f"Fetched {len(hits)} cases from GDC API")
    return hits


def run_bronze_cases(hits: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(extract_cases(hits))
    validate(df, BRONZE_CASES_SCHEMA, "bronze_cases")
    write_df_to_table(df, "bronze_cases", ACTIVE_ENGINE)
    print(f"bronze_cases — {len(df)} rows")
    return df


def run_bronze_samples(hits: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(extract_samples(hits))
    validate(df, BRONZE_SAMPLES_SCHEMA, "bronze_samples")
    write_df_to_table(df, "bronze_samples", ACTIVE_ENGINE)
    print(f"bronze_samples — {len(df)} rows")
    return df


def run_bronze_slides(hits: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(extract_slides(hits))
    validate(df, BRONZE_SLIDES_SCHEMA, "bronze_slides")
    write_df_to_table(df, "bronze_slides", ACTIVE_ENGINE)
    print(f"bronze_slides — {len(df)} rows")
    return df


# Silver layer
def run_silver_cases() -> pd.DataFrame:
    df = pd.read_sql("SELECT * FROM bronze_cases", ACTIVE_ENGINE)
    df = transform_silver(df)
    validate(df, SILVER_CASES_SCHEMA, "silver_cases")
    write_df_to_table(df, "silver_cases", ACTIVE_ENGINE)
    print(f"silver_cases — {df.shape}")
    return df


def run_silver_samples() -> pd.DataFrame:
    df = pd.read_sql("SELECT * FROM bronze_samples", ACTIVE_ENGINE)
    df = transform_silver(df)
    validate(df, SILVER_SAMPLES_SCHEMA, "silver_samples")
    write_df_to_table(df, "silver_samples", ACTIVE_ENGINE)
    print(f"silver_samples — {df.shape}")
    return df


# Gold layer
def run_gold_mastertable() -> pd.DataFrame:
    silver_cases   = pd.read_sql("SELECT * FROM silver_cases",   ACTIVE_ENGINE)
    silver_samples = pd.read_sql("SELECT * FROM silver_samples", ACTIVE_ENGINE)
    df = join_tables(silver_samples, silver_cases, on="case_id", how="left")
    validate(df, GOLD_MASTERTABLE_SCHEMA, "gold_mastertable")
    write_df_to_table(df, "gold_mastertable", ACTIVE_ENGINE)
    print(f"gold_mastertable — {df.shape}")
    return df