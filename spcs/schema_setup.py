# schema_setup.py
## Snowflake schema setup
### Run once before first pipeline execution to create the schema
### Schema and database are read from environment variables

import os
from config.database import ACTIVE_ENGINE
from sqlalchemy import text

def create_schema() -> None:
    """
    Creates the Snowflake schema if it does not already exist.
    Reads SNOWFLAKE_DATABASE and SNOWFLAKE_SCHEMA from environment.

    """
    database = os.getenv("SNOWFLAKE_DATABASE")
    schema   = os.getenv("SNOWFLAKE_SCHEMA")

    with ACTIVE_ENGINE.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {database}.{schema}"))
        print(f"Schema {database}.{schema} ready")