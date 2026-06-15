# extract.py
## Parses raw GDC API response into flat row dictionaries
### Each extract function handles one entity level — cases, samples, slides

from config.fields import CASE_FIELD_MAPPINGS, SAMPLE_FIELD_MAPPINGS, SLIDE_FIELD_MAPPINGS


def _extract_leaf(hit: dict, api_path: str):
    """
    Traverses a nested dict using a dot-separated api_path.
    Handles single nested dicts (e.g. project.project_id)
    and single-item lists (e.g. diagnoses.morphology).
    Sample and slide fields are handled separately.
    """
    keys = api_path.split(".")
    val  = hit
    for key in keys:
        if isinstance(val, dict):
            val = val.get(key)
        elif isinstance(val, list):
            val = val[0].get(key) if val else None
        else:
            return None
    return val

def extract_default(hits: list[dict]) -> list[dict]:
    """
    Flattens GDC default response into scalar fields.
    Lists are converted to comma separated strings.
    Used for bronze_landing table only.

    Usage:
        hits = fetch_default()
        rows = extract_default(hits)
    """
    rows = []
    for hit in hits:
        row = {}
        for key, val in hit.items():
            if isinstance(val, list):
                row[key] = ", ".join(str(v) for v in val)
            elif isinstance(val, dict):
                row[key] = str(val)
            else:
                row[key] = val
        rows.append(row)
    return rows

def extract_cases(hits: list[dict]) -> list[dict]:
    rows = []
    for hit in hits:
        row = {
            col_name: _extract_leaf(hit, api_path)
            for api_path, col_name, _ in CASE_FIELD_MAPPINGS
        }
        rows.append(row)
    return rows


def extract_samples(hits: list[dict]) -> list[dict]:
    sample_mappings = [
        (api_path.replace("samples.", "", 1), col_name)
        for api_path, col_name, _ in SAMPLE_FIELD_MAPPINGS
    ]
    rows = []
    for hit in hits:
        case_id = hit.get("case_id")
        for sample in hit.get("samples", []):
            row = {"case_id": case_id}
            for local_path, col_name in sample_mappings:
                row[col_name] = _extract_leaf(sample, local_path)
            rows.append(row)
    return rows


def extract_slides(hits: list[dict]) -> list[dict]:
    slide_mappings = [
        (api_path.replace("samples.portions.slides.", "", 1), col_name)
        for api_path, col_name, _ in SLIDE_FIELD_MAPPINGS
    ]
    rows = []
    for hit in hits:
        case_id = hit.get("case_id")
        for sample in hit.get("samples", []):
            sample_id = sample.get("sample_id")
            for portion in sample.get("portions", []):
                for slide in portion.get("slides", []):
                    row = {"case_id": case_id, "sample_id": sample_id}
                    for local_path, col_name in slide_mappings:
                        row[col_name] = _extract_leaf(slide, local_path)
                    rows.append(row)
    return rows