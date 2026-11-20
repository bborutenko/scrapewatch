"""watch(): argument validation, dispatch errors, double-wrap (no network)."""

import pytest
import requests

import scrapewatch as sw


def test_returns_a_working_session():
    watched = sw.watch(requests.Session(), job="ebay-prices")
    assert isinstance(watched, requests.Session)


def test_empty_job_is_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        sw.watch(requests.Session(), job="")


def test_double_wrap_returns_the_same_object():
    # interceptors.md §3: watch(watch(x)) returns x unchanged
    watched = sw.watch(requests.Session(), job="ebay-prices")

    again = sw.watch(watched, job="another-job")

    assert again is watched
