from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from svgmaker_proxy.clients.svgmaker_auth import SvgmakerSession
from svgmaker_proxy.core.config import Settings, get_settings
from svgmaker_proxy.models.generation import SvgmakerGenerateRequest

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
            "Content-Type": "application/json",
            "Accept-Language": self.settings.accept_language,
            "Authorization": f"Bearer {session.bearer_token}",
            "Cookie": cookie,
        }

    async def stream_generate(
        self,
        session: SvgmakerSession,
        request: SvgmakerGenerateRequest,
    ) -> AsyncIterator[SvgmakerGenerationEvent]:
        headers = self._base_headers(session)
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
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self.settings.svgmaker_origin}/api/generate",
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    raw = line.strip()
                    if not raw:
                        continue
                    if raw.startswith("data:"):
                        raw = raw[5:].strip()
                    try:
                        event_payload = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        raise SvgmakerGenerationError(
                            f"Invalid SSE payload: {raw}"
                        ) from exc
                    status = str(event_payload.get("status", "unknown"))
                    logger.info(
                        "Generation SSE event status=%s message=%r "
                        "credit_cost=%s generation_id=%s svg_url=%s",
                        status,
                        event_payload.get("message"),
                        event_payload.get("creditCost"),
                        event_payload.get("generationId"),
                        event_payload.get("svgUrl"),
                    )
                    yield SvgmakerGenerationEvent(status=status, payload=event_payload)

    async def generate_to_completion(
        self,
        session: SvgmakerSession,
        request: SvgmakerGenerateRequest,
    ) -> dict[str, Any]:
        final_payload: dict[str, Any] | None = None
        async for event in self.stream_generate(session, request):
            final_payload = event.payload
            if event.status == "complete":
                logger.info(
                    "Generation completed generation_id=%s credit_cost=%s svg_url=%s",
                    event.payload.get("generationId"),
                    event.payload.get("creditCost"),
                    event.payload.get("svgUrl"),
                )
                return event.payload
            if event.status == "error":
                raise SvgmakerGenerationError(str(event.payload))
        if final_payload is None:
            raise SvgmakerGenerationError("Generation stream returned no events")
        return final_payload
