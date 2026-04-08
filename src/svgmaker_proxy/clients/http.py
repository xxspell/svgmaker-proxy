from __future__ import annotations

import httpx

from svgmaker_proxy.core.config import Settings


def build_httpx_async_client(
    settings: Settings,
    timeout: httpx.Timeout | float,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        proxy=settings.http_proxy_url,
        trust_env=False,
    )
