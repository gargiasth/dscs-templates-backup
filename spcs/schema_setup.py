# schema_setup.py
## Snowflake schema setup
### Run once before first pipeline execution to create the schema
### Schema and database are read from environment variables

import os
import logging
from config.database import ACTIVE_ENGINE
from sqlalchemy import text

logger = logging.getLogger(__name__)

def create_schema() -> None:
    """
    Creates the Snowflake schema if it does not already exist.
    Reads SNOWFLAKE_DATABASE and SNOWFLAKE_SCHEMA from environment.

    """
    database = os.getenv("SNOWFLAKE_DATABASE")
    schema   = os.getenv("SNOWFLAKE_SCHEMA")

    try:
        with ACTIVE_ENGINE.connect() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {database}.{schema}"))
            logger.info(f"Schema {database}.{schema} ready")
    except Exception as e:
        logger.error(f"Failed to create schema {database}.{schema}: {e}")
        raise