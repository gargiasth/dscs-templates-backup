# definitions.py
## Dagster entry point
### Loads all assets and exposes them to the Dagster UI

from dagster import Definitions, load_assets_from_modules
from dagster import assets

all_assets = load_assets_from_modules([assets])

defs = Definitions(
    assets=all_assets,
)