# database.py
## Database engine setup and table registration
### Set ACTIVE_DATABASE environment variable to switch backends
### Supported backends: duckdb, postgres, snowflake

import os
from sqlalchemy import create_engine, Table, Column, MetaData, PrimaryKeyConstraint

from dotenv import load_dotenv
load_dotenv()

import logging
logger = logging.getLogger(__name__)


# Project paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

ACTIVE_DATABASE = os.getenv("ACTIVE_DATABASE", "snowflake")

if ACTIVE_DATABASE == "snowflake":
    try:
        from snowflake.sqlalchemy import URL  # type: ignore
        ACTIVE_ENGINE = create_engine(URL(
            account   = os.getenv("SNOWFLAKE_ACCOUNT"),
            user      = os.getenv("SNOWFLAKE_USER"),
            password  = os.getenv("SNOWFLAKE_PASSWORD"),
            database  = os.getenv("SNOWFLAKE_DATABASE"),
            schema    = os.getenv("SNOWFLAKE_SCHEMA"),
            warehouse = os.getenv("SNOWFLAKE_WAREHOUSE"),
            role      = os.getenv("SNOWFLAKE_ROLE"),
        ))
        from spcs.schema_setup import create_schema  # type: ignore
        create_schema()
    except Exception as e:
        logger.error(f"Failed to initialize Snowflake engine: {e}")
        raise

elif ACTIVE_DATABASE == "postgres":
    try:
        ACTIVE_ENGINE = create_engine(
            f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
            f"@{os.getenv('POSTGRES_HOST', 'postgres')}:{os.getenv('POSTGRES_PORT', '5432')}"
            f"/{os.getenv('POSTGRES_DB')}"
        )
    except Exception as e:
        logger.error(f"Failed to initialize Postgres engine: {e}")
        raise

elif ACTIVE_DATABASE == "duckdb":
    try:
        duckdb_file   = os.path.join("data", "gdc_pipeline.duckdb")
        ACTIVE_ENGINE = create_engine(f"duckdb:///{duckdb_file}")
    except Exception as e:
        logger.error(f"Failed to initialize DuckDB engine: {e}")
        raise

else:
    raise ValueError(f"Unknown ACTIVE_DATABASE: '{ACTIVE_DATABASE}'. Must be 'snowflake', 'postgres', or 'duckdb'.")

metadata = MetaData()


def _build_table(name: str, schema: dict) -> Table:
    columns = [Column(col_name, col_type) for col_name, col_type in schema["columns"].items()]
    pk = schema["pk"]
    if pk is not None:
        if isinstance(pk, list):
            columns.append(PrimaryKeyConstraint(*pk))
        else:
            columns.append(PrimaryKeyConstraint(pk))
    return Table(name, metadata, *columns)


def create_table(name: str, schema: dict) -> None:
    """
    Creates a single table in the active database from a schema definition.
    Safe to call multiple times — skips creation if table already exists.

    Usage:
        create_table("bronze_cases", BRONZE_CASES_SCHEMA)
    """
    try:
        table = _build_table(name, schema)
        metadata.create_all(ACTIVE_ENGINE, tables=[table])
        logger.info(f"Created table {name} on {ACTIVE_DATABASE}")
    except Exception as e:
        logger.error(f"Failed to create table {name}: {e}")
        raise