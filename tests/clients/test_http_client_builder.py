from __future__ import annotations

import httpx

from svgmaker_proxy.clients import http as http_module
from svgmaker_proxy.clients.http import build_httpx_async_client
from svgmaker_proxy.core.config import Settings


class _FakeAsyncClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


def test_build_httpx_client_without_proxy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def fake_async_client(**kwargs: object) -> _FakeAsyncClient:
        captured.update(kwargs)
        return _FakeAsyncClient(**kwargs)

    monkeypatch.setattr(http_module.httpx, "AsyncClient", fake_async_client)

    settings = Settings(_env_file=None)
    client = build_httpx_async_client(settings, timeout=5.0)

    assert isinstance(client, _FakeAsyncClient)
    assert captured["timeout"] == 5.0
    assert captured["proxy"] is None
    assert captured["trust_env"] is False


def test_build_httpx_client_with_proxy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def fake_async_client(**kwargs: object) -> _FakeAsyncClient:
        captured.update(kwargs)
        return _FakeAsyncClient(**kwargs)

    monkeypatch.setattr(http_module.httpx, "AsyncClient", fake_async_client)

    settings = Settings(HTTP_PROXY_URL="http://127.0.0.1:8080", _env_file=None)
    client = build_httpx_async_client(settings, timeout=httpx.Timeout(7.0))

    assert isinstance(client, _FakeAsyncClient)
    assert isinstance(captured["timeout"], httpx.Timeout)
    assert captured["proxy"] == "http://127.0.0.1:8080"
    assert captured["trust_env"] is False
