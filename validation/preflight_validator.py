"""
Orion Launchpad - preflight validation (run time, on the platform).

Checks that the containers a pipeline needs exist, creating them if they
don't. Runs once per job, in the `orion_preflight` task, before any stage.

Platform-agnostic by design:
  - the logic (check -> create if missing -> re-check -> stop with a clear
    error) is written once, in preflight();
  - each platform's SQL lives in _PLATFORMS, keyed by platform name;
  - the session is passed in, never created here. Anything with
    .sql(query).collect() works: a Spark session on Databricks, a Snowpark
    session on Snowflake.

Container names, per platform:
    Orion term   Databricks   Snowflake (to add)
    catalog      catalog      database
    schema       schema       schema
    volume       volume       stage

Public API:
    preflight(session, catalog, schema, volumes, platform="databricks") -> None
    ValidationError
"""

import logging

from utilities.logger import setup_logging

setup_logging()
log = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when a check fails and the task must stop."""


# ── Platform SQL ─────────────────────────────────────────────────────────────
# One entry per platform. Placeholders:
#   {catalog} {schema} {volume}       plain names (used inside LIKE '...')
#   {q_catalog} {q_schema} {q_volume} quoted identifiers
# Each step is (sql, privilege to ask an admin for). show_* must return a row
# when the object exists. use_* may be None if the platform has no such step.

_PLATFORMS = {
    "databricks": {
        "quote": "`",
        "words": {"catalog": "catalog", "schema": "schema", "volume": "volume"},
        "show_catalog":   ("SHOW CATALOGS LIKE '{catalog}'", None),
        "create_catalog": ("CREATE CATALOG IF NOT EXISTS {q_catalog}",
                           "CREATE CATALOG on the metastore"),
        "use_catalog":    ("USE CATALOG {q_catalog}", "USE CATALOG on {catalog}"),
        "show_schema":    ("SHOW SCHEMAS IN {q_catalog} LIKE '{schema}'", None),
        "create_schema":  ("CREATE SCHEMA IF NOT EXISTS {q_catalog}.{q_schema}",
                           "CREATE SCHEMA on {catalog}"),
        "use_schema":     ("USE SCHEMA {q_catalog}.{q_schema}", "USE SCHEMA on {catalog}.{schema}"),
        "show_volume":    ("SHOW VOLUMES IN {q_catalog}.{q_schema} LIKE '{volume}'", None),
        "create_volume":  ("CREATE VOLUME IF NOT EXISTS {q_catalog}.{q_schema}.{q_volume}",
                           "CREATE VOLUME on {catalog}.{schema}"),
    },
    # "snowflake": same keys — SHOW DATABASES / CREATE DATABASE / USE DATABASE,
    #              SHOW SCHEMAS IN DATABASE, SHOW STAGES IN SCHEMA / CREATE STAGE.
    #              Added with the Snowflake emitter, where it can be tested.
}


# ── Public API ───────────────────────────────────────────────────────────────

def preflight(session, catalog: str, schema: str, volumes, platform: str = "databricks") -> None:
    """Make sure catalog -> schema -> every volume exist, in that order.

    Creates whatever is missing. Raises ValidationError if something can't
    be created (usually a missing privilege, which the message names).
    """
    if platform not in _PLATFORMS:
        raise ValidationError(f"platform {platform!r} is not supported yet; "
                              f"choose one of {sorted(_PLATFORMS)}")
    sql = _PLATFORMS[platform]
    volumes = list(dict.fromkeys(v for v in volumes if v))   # drop blanks and repeats, keep order
    log.info("preflight on %s: %s.%s, volumes %s", platform, catalog, schema, volumes)

    names = _names(sql["quote"], catalog=catalog, schema=schema)
    _ensure(session, sql, "catalog", names)
    _use(session, sql, "catalog", names)
    _ensure(session, sql, "schema", names)
    _use(session, sql, "schema", names)
    for volume in volumes:
        _ensure(session, sql, "volume", _names(sql["quote"], catalog=catalog, schema=schema, volume=volume))

    log.info("preflight passed")


# ── Steps ────────────────────────────────────────────────────────────────────

def _names(quote: str, **plain) -> dict:
    """{catalog: 'c', q_catalog: '`c`', ...} for filling in the SQL templates."""
    quoted = {f"q_{k}": quote + v.replace(quote, quote * 2) + quote for k, v in plain.items()}
    return {**plain, **quoted}


def _label(sql, kind, names) -> str:
    """'catalog c', 'schema c.s', 'volume c.s.v' — in the platform's own words."""
    parts = [names["catalog"], names.get("schema"), names.get("volume")]
    depth = {"catalog": 1, "schema": 2, "volume": 3}[kind]
    return f"{sql['words'][kind]} {'.'.join(parts[:depth])}"


def _exists(session, query: str) -> bool:
    """True if a SHOW ... LIKE query returns at least one row."""
    return len(session.sql(query).collect()) > 0


def _run(session, query: str, privilege: str, what: str) -> None:
    """Run a statement; turn a permission failure into a clear ValidationError."""
    try:
        session.sql(query)
    except Exception as e:
        msg = str(e)
        if "PERMISSION_DENIED" in msg or "does not have" in msg.lower() or "insufficient privileges" in msg.lower():
            raise ValidationError(f"No permission for {what}. Ask an admin for {privilege}.") from e
        raise


def _ensure(session, sql, kind: str, names: dict) -> None:
    """Check one object; create it if missing; confirm it's there now."""
    show, _          = sql[f"show_{kind}"]
    create, privilege = sql[f"create_{kind}"]
    show, create, privilege = (s.format(**names) for s in (show, create, privilege))
    label = _label(sql, kind, names)

    if _exists(session, show):
        log.info("found %s", label)
        return
    _run(session, create, privilege, f"creating {label}")
    if not _exists(session, show):
        raise ValidationError(f"{label} was not created.")
    log.warning("Created %s", label)


def _use(session, sql, kind: str, names: dict) -> None:
    """Switch to the object. Also proves later tasks will be allowed to use it."""
    step = sql.get(f"use_{kind}")
    if step is None:
        return
    query, privilege = (s.format(**names) for s in step)
    _run(session, query, privilege, f"using {_label(sql, kind, names)}")