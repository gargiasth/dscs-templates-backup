# fetch.py
## GDC API data fetching
### Sends HTTP requests to the GDC API and returns raw JSON hits

import logging
import requests
import json
from config.api import GDC_CASES_URL
from config.fields import PROJECT_ID, RESULT_LIMIT, CASE_FIELDS

logger = logging.getLogger(__name__)


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
    logger.info(f"Fetching default fields from GDC API (project={project}, size={size})")
    try:
        response = requests.get(GDC_CASES_URL, params=params, timeout=(10, 60))
        response.raise_for_status()
        hits = response.json()["data"]["hits"]
    except Exception as e:
        logger.error(f"fetch_default failed: {e}")
        raise
    logger.info(f"fetch_default — received {len(hits)} hits")
    return hits

def fetch_cases(project: str = PROJECT_ID, size: int = RESULT_LIMIT) -> list[dict]:
    logger.info(f"Fetching cases from GDC API (project={project}, size={size})")
    params = _build_params(project=project, size=size)
    try:
        response = requests.get(GDC_CASES_URL, params=params, timeout=(10, 60))
        response.raise_for_status()
        hits = response.json()["data"]["hits"]
    except Exception as e:
        logger.error(f"fetch_cases failed: {e}")
        raise
    logger.info(f"fetch_cases — received {len(hits)} hits")
    return hits