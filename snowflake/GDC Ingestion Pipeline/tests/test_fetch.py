# test_fetch.py
## Unit tests for ingestion/fetch.py

import pytest
from unittest.mock import patch, MagicMock
from ingestion.fetch import fetch_cases, fetch_default


# Happy path tests — real API calls
def test_fetch_cases_returns_list():
    """fetch_cases returns a non-empty list"""
    hits = fetch_cases(size=5)
    assert isinstance(hits, list)
    assert len(hits) == 5


def test_fetch_cases_each_hit_is_dict():
    """each hit is a dictionary"""
    hits = fetch_cases(size=5)
    for hit in hits:
        assert isinstance(hit, dict)


def test_fetch_cases_has_case_id():
    """each hit contains a case_id"""
    hits = fetch_cases(size=5)
    for hit in hits:
        assert "case_id" in hit


def test_fetch_default_returns_list():
    """fetch_default returns a non-empty list"""
    hits = fetch_default(size=5)
    assert isinstance(hits, list)
    assert len(hits) == 5


def test_fetch_default_has_case_id():
    """each default hit contains a case_id"""
    hits = fetch_default(size=5)
    for hit in hits:
        assert "case_id" in hit


# Failure path tests — mocked API
def test_fetch_cases_raises_on_api_failure():
    """fetch_cases raises exception when API fails"""
    with patch("ingestion.fetch.requests.get") as mock_get:
        mock_get.return_value.raise_for_status.side_effect = Exception("API down")
        with pytest.raises(Exception, match="API down"):
            fetch_cases(size=5)


def test_fetch_default_raises_on_api_failure():
    """fetch_default raises exception when API fails"""
    with patch("ingestion.fetch.requests.get") as mock_get:
        mock_get.return_value.raise_for_status.side_effect = Exception("API down")
        with pytest.raises(Exception, match="API down"):
            fetch_default(size=5)


def test_fetch_cases_invalid_project_returns_empty():
    """fetch_cases with invalid project returns empty list"""
    hits = fetch_cases(project="INVALID-PROJECT", size=5)
    assert hits == []