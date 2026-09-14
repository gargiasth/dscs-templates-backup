"""
Postgres -> Snowflake SQL translation.

Known gap (not handled here): create_CDMv5_indices.sql contains
`CLUSTER <table> USING <index>` statements, which are Postgres-only
and don't even parse from the `postgres` dialect. Snowflake's nearest
equivalent is `ALTER TABLE ... CLUSTER BY`, a different mechanism, not
a drop-in translation. Not needed for table creation; flagging so it
doesn't surprise anyone reusing this against the indices file later.
"""
import sqlglot


def translate_postgres_to_snowflake(postgres_sql: str) -> list[str]:
    """
    Parse a Postgres SQL script and return each statement translated
    to Snowflake dialect, as a list of individual executable strings.
    """
    trees = sqlglot.parse(postgres_sql, read="postgres")
    return [tree.sql(dialect="snowflake") for tree in trees if tree is not None]