# helpers.py
## General purpose helper functions
### Reusable utilities for file system operations and database writes

import os
import pandas as pd


def ensure_dirs(*paths: str) -> None:

    """
    Creates one or more directories if they do not already exist.
    Safe to call multiple times; will not overwrite existing directories.

    Usage:
        ensure_dirs("data/")
        ensure_dirs("data/", "logs/", "output/")
    """

    for path in paths:
        os.makedirs(path, exist_ok=True)


def write_df_to_table(
    df: pd.DataFrame,
    table_name: str,
    engine,
    if_exists: str = "append"
) -> None:

    """
    Writes a DataFrame to a database table using the active SQLAlchemy engine.
    Defaults to append mode — existing rows are preserved.
    Pass if_exists="replace" to overwrite the table on each run.

    Usage:
        write_df_to_table(df, "bronze_cases", ACTIVE_ENGINE)
        write_df_to_table(df, "bronze_cases", ACTIVE_ENGINE, if_exists="replace")
    """

    df.to_sql(table_name, engine, if_exists=if_exists, index=False)
    print(f"Written {len(df)} rows to {table_name}")