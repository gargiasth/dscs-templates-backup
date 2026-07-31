# gold.py
## Gold layer transformation
### Reusable join and deduplication function for building wide tables
### Chain join_tables() calls to build any multi-entity mastertable
### If joining more that 1 table, to be called as a nested function 

import logging
import pandas as pd

logger = logging.getLogger(__name__)


def join_tables(
    left: pd.DataFrame,
    right: pd.DataFrame,
    on: str | list[str], # may be a single, on list of columns
    how: str = "left" #specify union type
) -> pd.DataFrame:
    df = left.merge(right, on=on, how=how)
    df.columns = df.columns.str.replace(r"_x$|_y$", "", regex=True)
    df = df.loc[:, ~df.columns.duplicated()]
    df = df.drop_duplicates(keep="last").reset_index(drop=True)
    logger.info(f"join_tables — {len(left)} left + {len(right)} right → {len(df)} rows ({how} join on {on})")
    return df