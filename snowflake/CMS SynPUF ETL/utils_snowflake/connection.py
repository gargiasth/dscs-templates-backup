"""
Shared Snowflake connection helper.

Connects at the account level only (no database/schema) — callers run
their own `USE DATABASE` / `USE SCHEMA` once those exist. This lets the
same connection function serve both "create the database" (which can't
specify a database that doesn't exist yet) and "create tables inside
an existing schema".
"""
import os
from dotenv import load_dotenv
import snowflake.connector

def get_connection():
    token_path = "/snowflake/session/token"
    if os.path.exists(token_path):
        # Running inside SPCS — use the auto-provisioned OAuth token
        with open(token_path, "r") as f:
            token = f.read()
        return snowflake.connector.connect(
            host=os.environ["SNOWFLAKE_HOST"],
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            token=token,
            authenticator="oauth",
        )
    else:
        # Running locally — use .env credentials, exactly as before
        return snowflake.connector.connect(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            password=os.environ["SNOWFLAKE_PASSWORD"],
            warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
            role=os.environ["SNOWFLAKE_ROLE"],
        )

def get_snowpark_session(conn):
    """
    Wraps an existing snowflake.connector Connection in a Snowpark
    Session, so put_stream (in-memory upload) is available without
    a second, separate connection.
    """
    from snowflake.snowpark import Session
    return Session.builder.configs({"connection": conn}).create()

