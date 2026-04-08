from __future__ import annotations

from svgmaker_proxy.clients import firebase_identity, svgmaker_auth
from svgmaker_proxy.clients.firebase_identity import FirebaseIdentityClient
from svgmaker_proxy.clients.svgmaker_auth import SvgmakerAuthClient
from svgmaker_proxy.core.config import Settings


def test_firebase_identity_client_uses_builder(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None)
    sentinel_client = object()
    captured: dict[str, object] = {"calls": 0}

    def fake_builder(settings_arg: Settings, *, timeout: float) -> object:
        captured["settings"] = settings_arg
        captured["timeout"] = timeout
        captured["calls"] = int(captured["calls"]) + 1
        return sentinel_client

    monkeypatch.setattr(firebase_identity, "build_httpx_async_client", fake_builder)

    client = FirebaseIdentityClient(settings=settings)
    built_first = client._client()
    built_second = client._client()

    assert built_first is sentinel_client
    assert built_second is sentinel_client
    assert built_first is built_second
    assert captured["settings"] is settings
    assert captured["timeout"] == settings.request_timeout_seconds
    assert captured["calls"] == 1


def test_svgmaker_auth_client_uses_builder(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None)
    sentinel_client = object()
    captured: dict[str, object] = {"calls": 0}

    def fake_builder(settings_arg: Settings, *, timeout: float) -> object:
        captured["settings"] = settings_arg
        captured["timeout"] = timeout
        captured["calls"] = int(captured["calls"]) + 1
        return sentinel_client

    monkeypatch.setattr(svgmaker_auth, "build_httpx_async_client", fake_builder)

    client = SvgmakerAuthClient(settings=settings)
    built_first = client._client()
    built_second = client._client()

    assert built_first is sentinel_client
    assert built_second is sentinel_client
    assert built_first is built_second
    assert captured["settings"] is settings
    assert captured["timeout"] == settings.request_timeout_seconds
    assert captured["calls"] == 1
