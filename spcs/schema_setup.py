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
    If the schema exists, skips creation and logs accordingly.
    Reads SNOWFLAKE_DATABASE and SNOWFLAKE_SCHEMA from environment.
    """
    database = os.getenv("SNOWFLAKE_DATABASE")
    schema   = os.getenv("SNOWFLAKE_SCHEMA")

    try:
        with ACTIVE_ENGINE.connect() as conn:
            result = conn.execute(text(
                f"SELECT COUNT(*) FROM information_schema.schemata "
                f"WHERE schema_name = '{schema}' AND catalog_name = '{database}'"
            ))
            exists = result.scalar() > 0

            if exists:
                logger.info(f"Schema {database}.{schema} already exists — skipping creation")
            else:
                conn.execute(text(f"CREATE SCHEMA {database}.{schema}"))
                logger.info(f"Schema {database}.{schema} created successfully")

    except Exception as e:
        logger.error(f"Failed to create schema {database}.{schema}: {e}")
        raise