from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from svgmaker_proxy.clients.http import build_httpx_async_client
from svgmaker_proxy.core.config import Settings, get_settings


class SvgmakerAuthError(RuntimeError):
    """Raised when an auth-related SVGMaker request fails."""


@dataclass(slots=True)
class SvgmakerSession:
    auth_token_id: str
    auth_token_refresh: str
    auth_token_sig: str
    bearer_token: str


class SvgmakerAuthClient:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._http_client = http_client
        self._owned_http_client: httpx.AsyncClient | None = None

    async def login(self, firebase_id_token: str) -> SvgmakerSession:
        client = self._client()
        response = await client.post(
            self._url("/api/auth/login"),
            content=b"",
            headers={
                **self._base_headers(),
                "Authorization": f"Bearer {firebase_id_token}",
                "Referer": f"{self.settings.svgmaker_base_url}/auth/register",
            },
        )
        payload = self._handle_json_response(response)
        if payload.get("success") is not True:
            raise SvgmakerAuthError(f"Unexpected login payload: {payload}")

        cookies = response.cookies
        auth_token_id = cookies.get("AuthToken.id")
        auth_token_refresh = cookies.get("AuthToken.refresh")
        auth_token_sig = cookies.get("AuthToken.sig")
        if not auth_token_id or not auth_token_refresh or not auth_token_sig:
            raise SvgmakerAuthError("SVGMaker login did not return AuthToken cookies")

        return SvgmakerSession(
            auth_token_id=auth_token_id,
            auth_token_refresh=auth_token_refresh,
            auth_token_sig=auth_token_sig,
            bearer_token=auth_token_id,
        )

    async def user_init(
        self,
        session: SvgmakerSession,
        firebase_local_id: str,
        display_name: str,
    ) -> dict[str, Any]:
        return await self._session_post_json(
            "/api/user-init",
            {
                "uid": firebase_local_id,
                "utmSource": None,
                "utmMedium": None,
                "displayName": display_name,
            },
            session=session,
        )

    async def check_daily_credits(self, session: SvgmakerSession) -> dict[str, Any]:
        return await self._session_post_json(
            "/api/check-daily-credits",
            None,
            session=session,
        )

    async def post_signup_survey(
        self,
        session: SvgmakerSession,
        profession: str = "Media Professional",
        heard_from: str = "Google",
    ) -> dict[str, Any]:
        return await self._session_post_json(
            "/api/survey/post-signup",
            {
                "profession": profession,
                "heardFrom": heard_from,
            },
            session=session,
        )

    async def complete_tour(
        self,
        session: SvgmakerSession,
        tour: str = "inputArea",
    ) -> dict[str, Any]:
        return await self._session_post_json(
            "/api/user/tour-completed",
            {"tour": tour},
            session=session,
        )

    async def update_preferences(
        self,
        session: SvgmakerSession,
        mode: str = "generate",
        quality: str | None = None,
        aspect_ratio: str | None = None,
        background: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "mode": mode,
            "preferences": {
                "selectedModels": [],
                "aspectRatio": aspect_ratio or self.settings.generate_aspect_ratio_default,
                "background": background or self.settings.generate_background_default,
                "quality": quality or self.settings.generate_quality_default,
            },
        }
        return await self._session_post_json(
            "/api/user/preferences",
            payload,
            session=session,
        )

    async def get_generation_info(
        self,
        session: SvgmakerSession,
        generation_id: str,
    ) -> dict[str, Any]:
        client = self._client()
        response = await client.get(
            self._url("/api/generation/info"),
            params={"generationId": generation_id},
            headers=self._session_headers(session),
        )
        return self._handle_json_response(response)

    async def get_vote_state(
        self,
        session: SvgmakerSession,
        generation_id: str,
        context: str = "personal",
    ) -> dict[str, Any]:
        client = self._client()
        response = await client.get(
            self._url("/api/vote"),
            params={"generationId": generation_id, "context": context},
            headers=self._session_headers(session),
        )
        return self._handle_json_response(response)

    async def _session_post_json(
        self,
        path: str,
        payload: dict[str, Any] | None,
        *,
        session: SvgmakerSession,
    ) -> dict[str, Any]:
        client = self._client()
        response = await client.post(
            self._url(path),
            json=payload,
            headers=self._session_headers(session),
        )
        return self._handle_json_response(response)

    def _session_headers(self, session: SvgmakerSession) -> dict[str, str]:
        cookie = "; ".join(
            [
                f"AuthToken.id={session.auth_token_id}",
                f"AuthToken.refresh={session.auth_token_refresh}",
                f"AuthToken.sig={session.auth_token_sig}",
            ]
        )
        return {
            **self._base_headers(),
            "Authorization": f"Bearer {session.bearer_token}",
            "Cookie": cookie,
            "Referer": f"{self.settings.svgmaker_base_url}/",
        }

    def _base_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.settings.user_agent,
            "Accept": "*/*",
            "Origin": self.settings.svgmaker_origin,
            "Content-Type": "application/json",
            "Accept-Language": self.settings.accept_language,
            "x-timezone": self.settings.timezone_header,
            "x-user-country": self.settings.user_country_header,
        }

    def _url(self, path: str) -> str:
        return f"{self.settings.svgmaker_base_url}{path}"

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is not None:
            return self._http_client
        if self._owned_http_client is None:
            self._owned_http_client = build_httpx_async_client(
                self.settings,
                timeout=self.settings.request_timeout_seconds,
            )
        return self._owned_http_client

    async def aclose(self) -> None:
        if self._owned_http_client is None:
            return
        await self._owned_http_client.aclose()
        self._owned_http_client = None

    def _handle_json_response(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise SvgmakerAuthError(
                f"Unexpected SVGMaker response ({response.status_code}): {response.text}"
            ) from exc

        if response.is_success:
            return payload

        raise SvgmakerAuthError(f"SVGMaker auth request failed: {payload}")
