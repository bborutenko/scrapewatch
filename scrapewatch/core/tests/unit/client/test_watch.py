"""watch(): argument validation and dispatch errors (no network)."""

import httpx
import pytest
import requests

import scrapewatch as sw


def test_returns_a_working_session():
    watched = sw.watch(requests.Session(), job="ebay-prices")
    assert isinstance(watched, requests.Session)


def test_empty_job_is_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        sw.watch(requests.Session(), job="")
