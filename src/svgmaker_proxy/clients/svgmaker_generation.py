from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from svgmaker_proxy.clients.http import build_httpx_async_client
from svgmaker_proxy.clients.svgmaker_auth import SvgmakerSession
from svgmaker_proxy.core.config import Settings, get_settings
from svgmaker_proxy.models.generation import SvgmakerEditRequest, SvgmakerGenerateRequest

logger = logging.getLogger(__name__)


class SvgmakerGenerationError(RuntimeError):
    """Raised when a generation request or SSE stream fails."""


@dataclass(slots=True)
class SvgmakerGenerationEvent:
    status: str
    payload: dict[str, Any]


class SvgmakerGenerationClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)

    def _base_headers(self, session: SvgmakerSession) -> dict[str, str]:
        cookie = "; ".join(
            [
                f"AuthToken.id={session.auth_token_id}",
                f"AuthToken.refresh={session.auth_token_refresh}",
                f"AuthToken.sig={session.auth_token_sig}",
            ]
        )
        return {
            "User-Agent": self.settings.user_agent,
            "Accept": "*/*",
            "Origin": self.settings.svgmaker_origin,
            "Referer": f"{self.settings.svgmaker_origin}/",
            "Accept-Language": self.settings.accept_language,
            "Authorization": f"Bearer {session.bearer_token}",
            "Cookie": cookie,
        }

    def _json_headers(self, session: SvgmakerSession) -> dict[str, str]:
        return {
            **self._base_headers(session),
            "Content-Type": "application/json",
        }

    def _parse_sse_payload(self, raw: str) -> SvgmakerGenerationEvent:
        if raw.startswith("data:"):
            raw = raw[5:].strip()
        try:
            event_payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SvgmakerGenerationError(f"Invalid SSE payload: {raw}") from exc
        status = str(event_payload.get("status", "unknown"))
        logger.info(
            "Generation SSE event status=%s message=%r credit_cost=%s generation_id=%s svg_url=%s",
            status,
            event_payload.get("message"),
            event_payload.get("creditCost"),
            event_payload.get("generationId"),
            event_payload.get("svgUrl"),
        )
        return SvgmakerGenerationEvent(status=status, payload=event_payload)

    async def _stream_response(
        self,
        response: httpx.Response,
    ) -> AsyncIterator[SvgmakerGenerationEvent]:
        response.raise_for_status()
        async for line in response.aiter_lines():
            raw = line.strip()
            if not raw or not raw.startswith("data:"):
                continue
            yield self._parse_sse_payload(raw)

    async def _consume_to_completion(
        self,
        events: AsyncIterator[SvgmakerGenerationEvent],
        *,
        operation_name: str,
    ) -> dict[str, Any]:
        saw_event = False
        async for event in events:
            saw_event = True
            if event.status == "complete":
                logger.info(
                    "%s completed generation_id=%s credit_cost=%s svg_url=%s",
                    operation_name,
                    event.payload.get("generationId"),
                    event.payload.get("creditCost"),
                    event.payload.get("svgUrl"),
                )
                return event.payload
            if event.status == "error":
                raise SvgmakerGenerationError(str(event.payload))
        if not saw_event:
            raise SvgmakerGenerationError(f"{operation_name} stream returned no events")
        raise SvgmakerGenerationError(f"{operation_name} stream ended before completion")

    def _build_edit_request(
        self,
        request: SvgmakerEditRequest,
    ) -> tuple[bool, dict[str, Any], dict[str, tuple[str, bytes, str]] | None]:
        source_svg_text = request.source_svg_text
        if source_svg_text and source_svg_text.strip():
            payload = {
                "prompt": request.prompt,
                "quality": request.quality,
                "aspectRatio": request.aspect_ratio,
                "background": request.background,
                "stream": request.stream,
                "base64Png": False,
                "svgText": request.svg_text,
                "image": source_svg_text,
            }
            return True, payload, None

        fields: dict[str, Any] = {
            "prompt": request.prompt,
            "quality": request.quality,
            "aspectRatio": request.aspect_ratio,
            "background": request.background,
            "stream": str(request.stream).lower(),
            "base64Png": "false",
            "svgText": str(request.svg_text).lower(),
        }
        files = {
            "image": (
                request.source_filename or "image.svg",
                request.source_file_content or b"",
                request.source_content_type or "image/svg+xml",
            )
        }
        return False, fields, files

    async def stream_edit(
        self,
        session: SvgmakerSession,
        request: SvgmakerEditRequest,
    ) -> AsyncIterator[SvgmakerGenerationEvent]:
        use_json, payload, files = self._build_edit_request(request)
        headers = self._json_headers(session) if use_json else self._base_headers(session)
        async with build_httpx_async_client(self.settings, timeout=self._timeout) as client:
            request_kwargs: dict[str, Any]
            if use_json:
                request_kwargs = {"json": payload}
            else:
                request_kwargs = {"data": payload, "files": files}
            async with client.stream(
                "POST",
                f"{self.settings.svgmaker_origin}/api/edit",
                headers=headers,
                **request_kwargs,
            ) as response:
                async for event in self._stream_response(response):
                    yield event

    async def edit_to_completion(
        self,
        session: SvgmakerSession,
        request: SvgmakerEditRequest,
    ) -> dict[str, Any]:
        return await self._consume_to_completion(
            self.stream_edit(session, request),
            operation_name="Edit",
        )

    async def stream_generate(
        self,
        session: SvgmakerSession,
        request: SvgmakerGenerateRequest,
    ) -> AsyncIterator[SvgmakerGenerationEvent]:
        headers = self._json_headers(session)
        payload = {
            "prompt": request.prompt,
            "quality": request.quality,
            "aspectRatio": request.aspect_ratio,
            "background": request.background,
            "stream": request.stream,
            "base64Png": request.base64_png,
            "svgText": request.svg_text,
            "styleParams": request.style_params,
        }
        logger.info(
            "Starting SVGMaker generation stream prompt=%r quality=%s "
            "aspect_ratio=%s background=%s",
            request.prompt,
            request.quality,
            request.aspect_ratio,
            request.background,
        )
        async with build_httpx_async_client(self.settings, timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self.settings.svgmaker_origin}/api/generate",
                headers=headers,
                json=payload,
            ) as response:
                async for event in self._stream_response(response):
                    yield event

    async def _generate_non_stream(
        self,
        session: SvgmakerSession,
        request: SvgmakerGenerateRequest,
    ) -> dict[str, Any]:
        headers = self._json_headers(session)
        payload = {
            "prompt": request.prompt,
            "quality": request.quality,
            "aspectRatio": request.aspect_ratio,
            "background": request.background,
            "stream": False,
            "base64Png": request.base64_png,
            "svgText": request.svg_text,
            "styleParams": request.style_params,
        }
        async with build_httpx_async_client(self.settings, timeout=self._timeout) as client:
            response = await client.post(
                f"{self.settings.svgmaker_origin}/api/generate",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            try:
                response_payload = response.json()
            except ValueError as exc:
                raise SvgmakerGenerationError(
                    "Generation non-stream response is not a JSON object"
                ) from exc
            if not isinstance(response_payload, dict):
                raise SvgmakerGenerationError(
                    "Generation non-stream response is not a JSON object"
                )
            return response_payload

    async def generate_to_completion(
        self,
        session: SvgmakerSession,
        request: SvgmakerGenerateRequest,
    ) -> dict[str, Any]:
        if not self.settings.stream_enabled:
            return await self._generate_non_stream(session, request)
        return await self._consume_to_completion(
            self.stream_generate(session, request),
            operation_name="Generation",
        )
