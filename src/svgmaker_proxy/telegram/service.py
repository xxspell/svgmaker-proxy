from __future__ import annotations

import base64
import binascii
import html
import logging
import os
import secrets
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from aiogram.types import User as TelegramApiUser

from svgmaker_proxy.clients.http import build_httpx_async_client
from svgmaker_proxy.core.config import Settings, get_settings
from svgmaker_proxy.models.generation import SvgmakerGenerateRequest
from svgmaker_proxy.models.telegram import (
    TelegramInviteCodeCreate,
    TelegramInviteCodeRecord,
    TelegramInviteCodeType,
    TelegramInviteCodeUpdate,
    TelegramUserCreate,
    TelegramUserRecord,
    TelegramUserUpdate,
)
from svgmaker_proxy.services.generation_proxy import GenerationProxyService, ProxiedGenerationResult
from svgmaker_proxy.storage.telegram_invite_code_repository import TelegramInviteCodeRepository
from svgmaker_proxy.storage.telegram_user_repository import TelegramUserRepository

logger = logging.getLogger(__name__)


class TelegramBotError(RuntimeError):
    """Raised when the Telegram bot service cannot fulfill a request."""


@dataclass(slots=True)
class TelegramQuotaDecision:
    user: TelegramUserRecord
    quota_remaining: int
    granted_today: bool
    is_unlimited: bool


@dataclass(slots=True)
class TelegramRenderResult:
    generation: ProxiedGenerationResult
    photo_bytes: bytes | None
    photo_filename: str | None
    svg_bytes: bytes | None
    svg_filename: str | None
    raw_link: str | None
    remaining_generations: int | None
    is_unlimited: bool


class TelegramBotService:
    def __init__(
        self,
        telegram_user_repository: TelegramUserRepository,
        telegram_invite_code_repository: TelegramInviteCodeRepository,
        generation_proxy: GenerationProxyService,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.telegram_user_repository = telegram_user_repository
        self.telegram_invite_code_repository = telegram_invite_code_repository
        self.generation_proxy = generation_proxy

    async def register_or_get_user(
        self,
        tg_user: TelegramApiUser,
        start_code: str | None = None,
    ) -> tuple[TelegramUserRecord, TelegramInviteCodeRecord | None]:
        existing = await self.telegram_user_repository.get_by_telegram_user_id(tg_user.id)
        invite = None
        if existing is None:
            invite = await self._resolve_invite_code(start_code)
            existing = await self.telegram_user_repository.create(
                TelegramUserCreate(
                    telegram_user_id=tg_user.id,
                    username=tg_user.username,
                    first_name=tg_user.first_name,
                    last_name=tg_user.last_name,
                    display_name=self._display_name(tg_user),
                    quota_remaining=self.settings.telegram_initial_generations,
                    initial_grant_applied=True,
                    started_with_code=invite.code if invite else None,
                    is_unlimited=(
                        invite is not None
                        and invite.code_type is TelegramInviteCodeType.unlimited
                    ),
                )
            )
            if invite is not None:
                await self.telegram_invite_code_repository.update(
                    invite.code,
                    TelegramInviteCodeUpdate(use_count=invite.use_count + 1),
                )
        else:
            invite = await self._maybe_apply_invite(existing, start_code)
            existing = await self.telegram_user_repository.update(
                tg_user.id,
                TelegramUserUpdate(
                    username=tg_user.username,
                    first_name=tg_user.first_name,
                    last_name=tg_user.last_name,
                    display_name=self._display_name(tg_user),
                ),
            ) or existing

        return existing, invite

    async def get_quota_decision(self, telegram_user_id: int) -> TelegramQuotaDecision:
        user = await self.telegram_user_repository.get_by_telegram_user_id(telegram_user_id)
        if user is None:
            raise TelegramBotError("Telegram user is not registered")

        granted_today = False
        if not user.is_unlimited:
            today = self._today()
            if user.quota_remaining <= 0 and user.last_daily_grant_on != today:
                user = await self.telegram_user_repository.update(
                    telegram_user_id,
                    TelegramUserUpdate(
                        quota_remaining=self.settings.telegram_daily_generations,
                        last_daily_grant_on=today,
                    ),
                ) or user
                granted_today = True

        return TelegramQuotaDecision(
            user=user,
            quota_remaining=user.quota_remaining,
            granted_today=granted_today,
            is_unlimited=user.is_unlimited,
        )

    async def generate_for_user(
        self,
        telegram_user_id: int,
        prompt: str,
    ) -> TelegramRenderResult:
        decision = await self.get_quota_decision(telegram_user_id)
        user = decision.user
        if not user.is_unlimited and user.quota_remaining <= 0:
            raise TelegramBotError(
                "Сейчас бесплатных генераций нет. Приходите завтра за следующей."
            )

        generation = await self.generation_proxy.generate(
            SvgmakerGenerateRequest(
                prompt=prompt,
                quality="high",
                aspect_ratio="auto",
                background="auto",
                stream=True,
                base64_png=True,
                svg_text=False,
                style_params={},
            )
        )

        if not user.is_unlimited:
            remaining_generations = max(0, user.quota_remaining - 1)
            await self.telegram_user_repository.update(
                telegram_user_id,
                TelegramUserUpdate(
                    quota_remaining=remaining_generations,
                    last_generation_at=self._utcnow(),
                ),
            )
        else:
            remaining_generations = None
            await self.telegram_user_repository.update(
                telegram_user_id,
                TelegramUserUpdate(last_generation_at=self._utcnow()),
            )

        photo_bytes = self._extract_base64_png(generation.raw_payload)
        raw_link = self._extract_raw_link(generation.raw_payload)
        svg_bytes = None
        svg_filename = None
        if generation.svg_url:
            svg_bytes = await self._download_bytes(generation.svg_url)
            svg_filename = f"svgmaker-{generation.generation_id or generation.request_id}.svg"
        if photo_bytes is None and svg_bytes is not None:
            photo_bytes = self._convert_svg_to_png(svg_bytes)

        return TelegramRenderResult(
            generation=generation,
            photo_bytes=photo_bytes,
            photo_filename=f"svgmaker-{generation.generation_id or generation.request_id}.png"
            if photo_bytes
            else None,
            svg_bytes=svg_bytes,
            svg_filename=svg_filename,
            raw_link=raw_link or generation.svg_url,
            remaining_generations=remaining_generations,
            is_unlimited=user.is_unlimited,
        )

    async def create_invite_code(self, description: str | None = None) -> TelegramInviteCodeRecord:
        code = self._generate_invite_code()
        return await self.telegram_invite_code_repository.create(
            TelegramInviteCodeCreate(
                code=code,
                code_type=TelegramInviteCodeType.unlimited,
                description=description,
                is_active=True,
            )
        )

    async def _resolve_invite_code(self, start_code: str | None) -> TelegramInviteCodeRecord | None:
        if not start_code:
            return None
        invite = await self.telegram_invite_code_repository.get_by_code(start_code)
        if invite is None or not invite.is_active:
            return None
        if invite.max_uses is not None and invite.use_count >= invite.max_uses:
            return None
        return invite

    async def _maybe_apply_invite(
        self,
        user: TelegramUserRecord,
        start_code: str | None,
    ) -> TelegramInviteCodeRecord | None:
        if user.is_unlimited or not start_code:
            return None
        invite = await self._resolve_invite_code(start_code)
        if invite is None:
            return None
        await self.telegram_user_repository.update(
            user.telegram_user_id,
            TelegramUserUpdate(
                started_with_code=invite.code,
                is_unlimited=invite.code_type is TelegramInviteCodeType.unlimited,
            ),
        )
        await self.telegram_invite_code_repository.update(
            invite.code,
            TelegramInviteCodeUpdate(use_count=invite.use_count + 1),
        )
        return invite

    def _extract_base64_png(self, payload: dict[str, Any]) -> bytes | None:
        for key in ("base64Png", "base64PNG", "pngBase64", "imageBase64", "rawBase64Png"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                raw = value.split(",", 1)[-1]
                try:
                    return base64.b64decode(raw)
                except (ValueError, binascii.Error):
                    continue
        return None

    def _extract_raw_link(self, payload: dict[str, Any]) -> str | None:
        for key in ("svgUrl", "rawUrl", "downloadUrl"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    async def _download_bytes(self, url: str) -> bytes | None:
        try:
            async with build_httpx_async_client(self.settings, timeout=60.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.content
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to download generation artifact from %s: %s", url, exc)
            return None

    def format_result_caption(self, result: TelegramRenderResult) -> str:
        lines = ["Готово."]
        if result.is_unlimited:
            lines.append("Осталось генераций: безлимит")
        elif result.remaining_generations is not None:
            lines.append(f"Осталось генераций: {result.remaining_generations}")
        if result.raw_link:
            lines.append(f'<a href="{html.escape(result.raw_link, quote=True)}">SVG</a>')
        return "\n".join(lines)

    def _convert_svg_to_png(self, svg_bytes: bytes) -> bytes | None:
        try:
            self._configure_macos_cairo_paths()
            import cairosvg

            return cairosvg.svg2png(bytestring=svg_bytes)
        except (ImportError, OSError) as exc:
            logger.warning("SVG to PNG conversion is unavailable in this environment: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to convert SVG to PNG: %s", exc)
            return None

    def _generate_invite_code(self) -> str:
        return secrets.token_urlsafe(24)

    def _display_name(self, tg_user: TelegramApiUser) -> str:
        if tg_user.full_name:
            return tg_user.full_name
        if tg_user.username:
            return tg_user.username
        return str(tg_user.id)

    def _today(self) -> date:
        return datetime.now(UTC).date()

    def _utcnow(self) -> datetime:
        return datetime.now(UTC)

    def _configure_macos_cairo_paths(self) -> None:
        if sys.platform != "darwin":
            return

        candidates = [
            Path("/opt/homebrew/opt/cairo/lib"),
            Path("/opt/homebrew/lib"),
            Path("/usr/local/opt/cairo/lib"),
            Path("/usr/local/lib"),
        ]
        existing = [str(path) for path in candidates if path.exists()]
        if not existing:
            return

        current = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        current_parts = [part for part in current.split(":") if part]
        merged = []
        for part in [*existing, *current_parts]:
            if part not in merged:
                merged.append(part)
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(merged)
