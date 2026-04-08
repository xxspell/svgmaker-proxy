from __future__ import annotations

from typing import Any

import pytest

from svgmaker_proxy.clients import svgmaker_generation
from svgmaker_proxy.clients.svgmaker_auth import SvgmakerSession
from svgmaker_proxy.clients.svgmaker_generation import SvgmakerGenerationClient, SvgmakerGenerationError
from svgmaker_proxy.core.config import Settings
from svgmaker_proxy.models.generation import SvgmakerGenerateRequest


class _FakeJsonResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _FakeGenerationHttpClient:
    def __init__(self, response: _FakeJsonResponse) -> None:
        self._response = response
        self.post_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeGenerationHttpClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        return False

    async def post(self, url: str, **kwargs: Any) -> _FakeJsonResponse:
        self.post_calls.append({"url": url, **kwargs})
        return self._response

    def stream(self, method: str, url: str, **kwargs: Any) -> Any:
        self.stream_calls.append({"method": method, "url": url, **kwargs})
        raise AssertionError("stream() should not be called when non-stream mode is enabled")


@pytest.mark.asyncio
async def test_generate_to_completion_uses_json_when_stream_disabled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None, SVGM_STREAM_ENABLED=False)

    expected_payload = {"status": "complete", "generationId": "g-123", "svgUrl": "https://example.com/g-123.svg"}
    fake_http_client = _FakeGenerationHttpClient(_FakeJsonResponse(expected_payload))

    monkeypatch.setattr(
        svgmaker_generation,
        "build_httpx_async_client",
        lambda settings_arg, timeout: fake_http_client,
    )

    client = SvgmakerGenerationClient(settings=settings)
    session = SvgmakerSession(
        auth_token_id="id",
        auth_token_refresh="refresh",
        auth_token_sig="sig",
        bearer_token="bearer",
    )
    request = SvgmakerGenerateRequest(prompt="cat", stream=True)

    result = await client.generate_to_completion(session, request)

    assert result == expected_payload
    assert fake_http_client.stream_calls == []
    assert len(fake_http_client.post_calls) == 1
    call = fake_http_client.post_calls[0]
    assert call["url"].endswith("/api/generate")
    assert call["json"]["stream"] is False


@pytest.mark.asyncio
async def test_generate_non_stream_raises_on_error_status(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None, SVGM_STREAM_ENABLED=False)
    fake_http_client = _FakeGenerationHttpClient(
        _FakeJsonResponse({"status": "error", "message": "no credits"})
    )

    monkeypatch.setattr(
        svgmaker_generation,
        "build_httpx_async_client",
        lambda settings_arg, timeout: fake_http_client,
    )

    client = SvgmakerGenerationClient(settings=settings)
    session = SvgmakerSession(
        auth_token_id="id",
        auth_token_refresh="refresh",
        auth_token_sig="sig",
        bearer_token="bearer",
    )

    with pytest.raises(SvgmakerGenerationError):
        await client.generate_to_completion(session, SvgmakerGenerateRequest(prompt="cat"))
