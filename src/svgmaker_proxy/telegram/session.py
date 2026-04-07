from __future__ import annotations

from aiogram.client.session.aiohttp import AiohttpSession


def build_bot_session(proxy_url: str | None) -> AiohttpSession | None:
    if not proxy_url:
        return None
    return AiohttpSession(proxy=proxy_url)
