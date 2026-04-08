from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from svgmaker_proxy.clients import svgmaker_generation
from svgmaker_proxy.clients.svgmaker_auth import SvgmakerSession
from svgmaker_proxy.clients.svgmaker_generation import (
    SvgmakerGenerationClient,
    SvgmakerGenerationError,
)
from svgmaker_proxy.core.config import Settings
from svgmaker_proxy.models.generation import SvgmakerEditRequest, SvgmakerGenerateRequest
from svgmaker_proxy.telegram import service as telegram_service
from svgmaker_proxy.telegram.service import TelegramBotService


class _FakeSseResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


class _FakeStreamContext:
    def __init__(self, response: _FakeSseResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeSseResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        return False


class _FakeGenerationHttpClient:
    def __init__(self, response: _FakeSseResponse) -> None:
        self._response = response
        self.stream_calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeGenerationHttpClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        return False

    def stream(self, method: str, url: str, **kwargs: Any) -> _FakeStreamContext:
        self.stream_calls.append({"method": method, "url": url, **kwargs})
        return _FakeStreamContext(self._response)


class _FakeDownloadResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakeTelegramHttpClient:
    def __init__(self, response: _FakeDownloadResponse) -> None:
        self._response = response
        self.requested_urls: list[str] = []

    async def __aenter__(self) -> _FakeTelegramHttpClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        return False

    async def get(self, url: str) -> _FakeDownloadResponse:
        self.requested_urls.append(url)
        return self._response


@pytest.mark.asyncio
async def test_generation_stream_generate_uses_http_builder(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None)
    sse_response = _FakeSseResponse(['data: {"status":"complete","generationId":"g-1"}'])
    fake_http_client = _FakeGenerationHttpClient(sse_response)
    captured: dict[str, object] = {"calls": 0}

    def fake_builder(*, settings_arg: Settings, timeout: object) -> _FakeGenerationHttpClient:
        captured["calls"] = int(captured["calls"]) + 1
        captured["settings"] = settings_arg
        captured["timeout"] = timeout
        return fake_http_client

    monkeypatch.setattr(
        svgmaker_generation,
        "build_httpx_async_client",
        lambda settings_arg, timeout: fake_builder(settings_arg=settings_arg, timeout=timeout),
    )

    client = SvgmakerGenerationClient(settings=settings)
    session = SvgmakerSession(
        auth_token_id="id",
        auth_token_refresh="refresh",
        auth_token_sig="sig",
        bearer_token="bearer",
    )
    request = SvgmakerGenerateRequest(prompt="cat")

    events = [event async for event in client.stream_generate(session, request)]

    assert len(events) == 1
    assert events[0].status == "complete"
    assert captured["calls"] == 1
    assert captured["settings"] is settings
    assert captured["timeout"] is client._timeout


@pytest.mark.asyncio
async def test_generation_stream_edit_uses_http_builder(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None)
    sse_response = _FakeSseResponse(['data: {"status":"complete","generationId":"e-1"}'])
    fake_http_client = _FakeGenerationHttpClient(sse_response)
    captured: dict[str, object] = {"calls": 0}

    def fake_builder(*, settings_arg: Settings, timeout: object) -> _FakeGenerationHttpClient:
        captured["calls"] = int(captured["calls"]) + 1
        captured["settings"] = settings_arg
        captured["timeout"] = timeout
        return fake_http_client

    monkeypatch.setattr(
        svgmaker_generation,
        "build_httpx_async_client",
        lambda settings_arg, timeout: fake_builder(settings_arg=settings_arg, timeout=timeout),
    )

    client = SvgmakerGenerationClient(settings=settings)
    session = SvgmakerSession(
        auth_token_id="id",
        auth_token_refresh="refresh",
        auth_token_sig="sig",
        bearer_token="bearer",
    )
    request = SvgmakerEditRequest(prompt="edit", source_svg_text="<svg/>", svg_text=True)

    events = [event async for event in client.stream_edit(session, request)]

    assert len(events) == 1
    assert events[0].status == "complete"
    assert captured["calls"] == 1
    assert captured["settings"] is settings
    assert captured["timeout"] is client._timeout


def test_build_edit_request_uses_multipart_when_source_svg_text_is_empty() -> None:
    client = SvgmakerGenerationClient(settings=Settings(_env_file=None))
    request = SvgmakerEditRequest(
        prompt="edit",
        source_svg_text="",
        source_file_content=b"<svg></svg>",
        source_filename="input.svg",
        source_content_type="image/svg+xml",
    )

    use_json, _payload, files = client._build_edit_request(request)

    assert use_json is False
    assert files is not None


@pytest.mark.asyncio
async def test_telegram_download_uses_http_builder(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(_env_file=None)
    fake_http_client = _FakeTelegramHttpClient(_FakeDownloadResponse(b"svg-bytes"))
    captured: dict[str, object] = {"calls": 0}

    def fake_builder(*, settings_arg: Settings, timeout: object) -> _FakeTelegramHttpClient:
        captured["calls"] = int(captured["calls"]) + 1
        captured["settings"] = settings_arg
        captured["timeout"] = timeout
        return fake_http_client

    monkeypatch.setattr(
        telegram_service,
        "build_httpx_async_client",
        lambda settings_arg, timeout: fake_builder(settings_arg=settings_arg, timeout=timeout),
    )

    service = TelegramBotService(
        telegram_user_repository=object(),  # type: ignore[arg-type]
        telegram_invite_code_repository=object(),  # type: ignore[arg-type]
        generation_proxy=object(),  # type: ignore[arg-type]
        settings=settings,
    )

    result = await service._download_bytes("https://example.com/result.svg")

    assert result == b"svg-bytes"
    assert fake_http_client.requested_urls == ["https://example.com/result.svg"]
    assert captured["calls"] == 1
    assert captured["settings"] is settings
    assert captured["timeout"] == 60.0


@pytest.mark.asyncio
async def test_generation_stream_ignores_non_data_sse_lines() -> None:
    client = SvgmakerGenerationClient(settings=Settings(_env_file=None))
    response = _FakeSseResponse(
        [
            "event: message",
            ": keepalive",
            "id: 1",
            'data: {"status":"working","generationId":"g-1"}',
            'data: {"status":"complete","generationId":"g-1"}',
        ]
    )

    events = [event async for event in client._stream_response(response)]

    assert [event.status for event in events] == ["working", "complete"]


@pytest.mark.asyncio
async def test_generation_to_completion_requires_complete_status() -> None:
    client = SvgmakerGenerationClient(settings=Settings(_env_file=None))

    async def _events() -> AsyncIterator[svgmaker_generation.SvgmakerGenerationEvent]:
        yield svgmaker_generation.SvgmakerGenerationEvent(
            status="working",
            payload={"status": "working", "generationId": "g-1"},
        )

    with pytest.raises(SvgmakerGenerationError, match="ended before completion"):
        await client._consume_to_completion(_events(), operation_name="Generation")
