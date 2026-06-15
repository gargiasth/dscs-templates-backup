# silver.py
## Silver layer transformation
### Reusable cleaning function applied to all entity DataFrames
### Replaces known null placeholders, deduplicates, and resets index

import pandas as pd

NULL_VALUES = [
    "Not Reported", "Unknown", "not reported", "unknown",
    "N/A", "NA", "--", "Not Applicable"
]

def transform_silver(df: pd.DataFrame) -> pd.DataFrame:
    df = df.drop_duplicates(keep="first").reset_index(drop=True)
    df = df.replace(NULL_VALUES, pd.NA)

    return df