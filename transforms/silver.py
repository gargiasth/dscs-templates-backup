# silver.py
## Silver layer transformation
### Reusable cleaning function applied to all entity DataFrames
### Replaces known null placeholders, deduplicates, and resets index

import logging
import pandas as pd

logger = logging.getLogger(__name__)

NULL_VALUES = [
    "Not Reported", "Unknown", "not reported", "unknown",
    "N/A", "NA", "--", "Not Applicable"
]

def transform_silver(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    df = df.drop_duplicates(keep="first").reset_index(drop=True)
    dupes_dropped = before - len(df)
    df = df.replace(NULL_VALUES, pd.NA)
    logger.info(f"transform_silver — {len(df)} rows ({dupes_dropped} duplicates dropped)")
    return df