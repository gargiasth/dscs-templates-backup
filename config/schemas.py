# schemas.py
## Table schemas derived automatically from fields.py
### To change a schema update the relevant mappings, pk or fk in fields.py
### Bronze tables have no pk — raw landing zone
### Silver and gold pks and fks are defined in fields.py

from sqlalchemy import String
from config.fields import *   # all mappings


def _derive_schema(mappings: list, pk, fk: list) -> dict:
    return {
        "pk":      pk,
        "fk":      fk,
        "columns": {col_name: col_type for _, col_name, col_type in mappings}
    }


def infer_schema(record: dict) -> dict:
    """
    Infers a schema from a single API response record.
    All columns default to String type.
    Used for bronze_landing table only.

    Usage:
        schema = infer_schema(rows[0])
    """
    return {"pk": None, "fk": [], "columns": {key: String for key in record.keys()}}


# Bronze schemas — no pk or fk
BRONZE_CASES_SCHEMA   = _derive_schema(CASE_FIELD_MAPPINGS,   pk=None, fk=[])
BRONZE_SAMPLES_SCHEMA = _derive_schema(SAMPLE_FIELD_MAPPINGS, pk=None, fk=[])
BRONZE_SLIDES_SCHEMA  = _derive_schema(SLIDE_FIELD_MAPPINGS,  pk=None, fk=[])

# Silver schemas — pk and fk from fields.py
SILVER_CASES_SCHEMA   = _derive_schema(SILVER_CASE_FIELD_MAPPINGS,   pk=CASE_PK,   fk=CASE_FK)
SILVER_SAMPLES_SCHEMA = _derive_schema(SILVER_SAMPLE_FIELD_MAPPINGS, pk=SAMPLE_PK, fk=SAMPLE_FK)
# Gold schema — cases and samples combined
GOLD_MASTERTABLE_SCHEMA = {
    "pk": SAMPLE_PK,
    "fk": [],
    "columns": {
        **{col_name: col_type for _, col_name, col_type in CASE_FIELD_MAPPINGS},
        **{col_name: col_type for _, col_name, col_type in SAMPLE_FIELD_MAPPINGS},
    }
}