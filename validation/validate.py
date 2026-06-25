# validate.py
## Schema and data validation functions using pandera
### Called between pipeline layers to catch data issues early
### Raises pandera.errors.SchemaError if validation fails — pipeline stops immediately

import logging
import pandas as pd
import pandera as pa
from pandera import Column, DataFrameSchema, Check
from sqlalchemy import String, Float

logger = logging.getLogger(__name__)


def _build_pandera_schema(schema: dict) -> DataFrameSchema:
    """
    Builds a pandera DataFrameSchema from a pipeline schema dict.
    pk columns are set to nullable=False, all others nullable=True.

    Usage:
        pandera_schema = _build_pandera_schema(SILVER_CASES_SCHEMA)
    """
    pk  = schema["pk"]
    columns = {}

    for col_name, col_type in schema["columns"].items():
        is_pk     = (col_name == pk) or (isinstance(pk, list) and col_name in pk)
        nullable  = not is_pk

        if col_type == Float:
            columns[col_name] = Column(float, nullable=nullable, coerce=True)
        else:
            columns[col_name] = Column(str, nullable=nullable, coerce=True)

    return DataFrameSchema(columns, strict=False)


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
    Runs all validations for a given layer using pandera.
    Checks row count, column presence, types and pk nullability.

    Usage:
        validate(df, BRONZE_CASES_SCHEMA, "bronze_cases")
        validate(df, SILVER_CASES_SCHEMA, "silver_cases", min_rows=500)
    """
    validate_row_count(df, min_rows, layer)

    pandera_schema = _build_pandera_schema(schema)

    try:
        pandera_schema.validate(df)
        logger.info(f"{layer} — validation passed ({len(df)} rows)")
    except pa.errors.SchemaError as e:
        raise pa.errors.SchemaError(
            schema=e.schema,
            data=e.data,
            message=f"{layer} — validation failed: {e.args[0]}",
            failure_cases=e.failure_cases,
            check=e.check,
        )