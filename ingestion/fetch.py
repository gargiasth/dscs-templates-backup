# fetch.py
## GDC API data fetching
### Sends HTTP requests to the GDC API and returns raw JSON hits

import requests
import json
from config.api import GDC_CASES_URL
from config.fields import PROJECT_ID, RESULT_LIMIT, CASE_FIELDS


def _build_params(project: str, size: int) -> dict:
    return {
        "filters": json.dumps({
            "op": "in",
            "content": {
                "field": "project.project_id",
                "value": [project],
            }
        }),
        "fields": ",".join(CASE_FIELDS),
        "format": "JSON",
        "size":   str(size),
    }

def fetch_default(project: str = PROJECT_ID, size: int = RESULT_LIMIT) -> list[dict]:
    """
    Fetches GDC default fields — no fields param specified.
    Use this to explore what GDC returns before defining field mappings.
    Results land in bronze_landing table.

    Usage:
        hits = fetch_default()
    """
    params = {
        "filters": json.dumps({
            "op": "in",
            "content": {
                "field": "project.project_id",
                "value": [project],
            }
        }),
        "format": "JSON",
        "size":   str(size),
    }
    response = requests.get(GDC_CASES_URL, params=params, timeout=(10, 60))
    response.raise_for_status()
    return response.json()["data"]["hits"]

def fetch_cases(project: str = PROJECT_ID, size: int = RESULT_LIMIT) -> list[dict]:
    params   = _build_params(project=project, size=size)
    response = requests.get(GDC_CASES_URL, params=params, timeout=(10, 60))
    response.raise_for_status()
    return response.json()["data"]["hits"]