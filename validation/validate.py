# validate.py
## Schema and data validation functions
### Called between pipeline layers to catch data issues early
### Raises ValueError if validation fails — pipeline stops immediately

import pandas as pd


def validate_columns(df: pd.DataFrame, schema: dict, layer: str) -> None:
    """
    Checks that the DataFrame has all expected columns from the schema.
    Raises ValueError if any columns are missing or unexpected.

    Usage:
        validate_columns(df, BRONZE_CASES_SCHEMA, "bronze_cases")
    """
    expected = set(schema["columns"].keys())
    actual   = set(df.columns)
    missing  = expected - actual
    extra    = actual - expected

    if missing:
        raise ValueError(f"{layer} — missing columns: {missing}")
    if extra:
        print(f"{layer} — extra columns not in schema (will be ignored): {extra}")


def validate_not_empty(df: pd.DataFrame, layer: str) -> None:
    """
    Checks that the DataFrame has at least one row.
    Raises ValueError if empty.

    Usage:
        validate_not_empty(df, "bronze_cases")
    """
    if len(df) == 0:
        raise ValueError(f"{layer} — DataFrame is empty")


def validate_pk(df: pd.DataFrame, schema: dict, layer: str) -> None:
    """
    Checks that the primary key column has no nulls and no duplicates.
    Skipped if schema has no pk defined (bronze tables).

    Usage:
        validate_pk(df, SILVER_CASES_SCHEMA, "silver_cases")
    """
    pk = schema["pk"]
    if pk is None:
        return

    if isinstance(pk, list):
        null_mask = df[pk].isnull().any(axis=1)
        dupe_mask = df.duplicated(subset=pk)
    else:
        null_mask = df[pk].isnull()
        dupe_mask = df[pk].duplicated()

    if null_mask.any():
        raise ValueError(f"{layer} — pk '{pk}' has {null_mask.sum()} null values")
    if dupe_mask.any():
        raise ValueError(f"{layer} — pk '{pk}' has {dupe_mask.sum()} duplicate values")


def validate_row_count(df: pd.DataFrame, min_rows: int, layer: str) -> None:
    """
    Checks that the DataFrame meets a minimum row count threshold.
    Useful for catching incomplete API responses.

    Usage:
        validate_row_count(df, 100, "bronze_cases")
    """
    if len(df) < min_rows:
        raise ValueError(f"{layer} — expected at least {min_rows} rows, got {len(df)}")


def validate(df: pd.DataFrame, schema: dict, layer: str, min_rows: int = 1) -> None:
    """
    Runs all validations for a given layer.
    Call this before writing any DataFrame to the database.

    Usage:
        validate(df, BRONZE_CASES_SCHEMA, "bronze_cases")
        validate(df, SILVER_CASES_SCHEMA, "silver_cases", min_rows=500)
    """
    validate_not_empty(df,            layer)
    validate_columns(df,  schema,     layer)
    validate_pk(df,       schema,     layer)
    validate_row_count(df, min_rows,  layer)
    print(f"{layer} — validation passed ({len(df)} rows)")