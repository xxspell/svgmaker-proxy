from __future__ import annotations

from typing import Any

import pytest

from svgmaker_proxy.clients import svgmaker_generation
from svgmaker_proxy.clients.svgmaker_auth import SvgmakerSession
from svgmaker_proxy.clients.svgmaker_generation import SvgmakerGenerationClient, SvgmakerGenerationError
from svgmaker_proxy.core.config import Settings
from svgmaker_proxy.models.generation import SvgmakerEditRequest, SvgmakerGenerateRequest


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
async def test_edit_to_completion_uses_json_when_stream_disabled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None, SVGM_STREAM_ENABLED=False)

    expected_payload = {
        "status": "complete",
        "generationId": "e-123",
        "svgUrl": "https://example.com/e-123.svg",
    }
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
    request = SvgmakerEditRequest(
        prompt="tweak logo",
        stream=True,
        source_svg_text="<svg viewBox='0 0 10 10'></svg>",
    )

    result = await client.edit_to_completion(session, request)

    assert result == expected_payload
    assert fake_http_client.stream_calls == []
    assert len(fake_http_client.post_calls) == 1
    call = fake_http_client.post_calls[0]
    assert call["url"].endswith("/api/edit")
    assert call["json"]["stream"] is False
    assert call["json"]["image"] == "<svg viewBox='0 0 10 10'></svg>"


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


@pytest.mark.asyncio
async def test_generate_non_stream_accepts_success_payload_without_status(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None, SVGM_STREAM_ENABLED=False)
    success_payload = {
        "generationId": "g-123",
        "svgUrl": "https://example.com/g-123.svg",
        "creditCost": 3,
    }
    fake_http_client = _FakeGenerationHttpClient(_FakeJsonResponse(success_payload))

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

    result = await client.generate_to_completion(session, SvgmakerGenerateRequest(prompt="cat"))

    assert result == success_payload


@pytest.mark.asyncio
async def test_generate_non_stream_missing_status_error_is_short(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None, SVGM_STREAM_ENABLED=False)
    huge_payload = {
        "base64Png": "x" * 6000,
    }
    fake_http_client = _FakeGenerationHttpClient(_FakeJsonResponse(huge_payload))

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

    with pytest.raises(SvgmakerGenerationError) as exc_info:
        await client.generate_to_completion(session, SvgmakerGenerateRequest(prompt="cat"))

    assert "ended before completion" in str(exc_info.value)
    assert "<omitted>" in str(exc_info.value)
    assert len(str(exc_info.value)) < 1000


@pytest.mark.asyncio
async def test_edit_non_stream_raises_on_error_status(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None, SVGM_STREAM_ENABLED=False)
    fake_http_client = _FakeGenerationHttpClient(
        _FakeJsonResponse({"status": "error", "message": "invalid image"})
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
        await client.edit_to_completion(
            session,
            SvgmakerEditRequest(prompt="tweak logo", source_svg_text="<svg />"),
        )


@pytest.mark.asyncio
async def test_generate_non_stream_raises_on_non_dict_json(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None, SVGM_STREAM_ENABLED=False)
    fake_http_client = _FakeGenerationHttpClient(_FakeJsonResponse(["bad"]))

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

    with pytest.raises(SvgmakerGenerationError, match="not a JSON object"):
        await client.generate_to_completion(session, SvgmakerGenerateRequest(prompt="cat"))


@pytest.mark.asyncio
async def test_edit_non_stream_raises_on_non_dict_json(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None, SVGM_STREAM_ENABLED=False)
    fake_http_client = _FakeGenerationHttpClient(_FakeJsonResponse(["bad"]))

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

    with pytest.raises(SvgmakerGenerationError, match="not a JSON object"):
        await client.edit_to_completion(
            session,
            SvgmakerEditRequest(prompt="tweak logo", source_svg_text="<svg />"),
        )
