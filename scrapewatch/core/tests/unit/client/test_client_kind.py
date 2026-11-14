"""client_kind(): name-based dispatch over SUPPORTED_CLIENTS, no imports."""

import httpx
import requests

import scrapewatch as sw


def test_recognizes_requests_session():
    assert sw.client_kind(requests.Session()) == "requests"


def test_recognizes_httpx_sync_and_async():
    assert sw.client_kind(httpx.Client()) == "httpx"
    assert sw.client_kind(httpx.AsyncClient()) == "httpx"


def test_recognizes_subclasses_via_mro():
    class MySession(requests.Session): ...

    assert sw.client_kind(MySession()) == "requests"


def test_recognizes_wrapped_session():
    watched = sw.watch(requests.Session(), job="t")
    assert sw.client_kind(watched) == "requests"


def test_unknown_objects_are_none():
    assert sw.client_kind(object()) is None
    assert sw.client_kind("not a client") is None

