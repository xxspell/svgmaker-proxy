from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest


async def _async_noop(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
    return None


@pytest.mark.asyncio
async def test_run_stack_uses_proxy_session(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    session_obj = object()

    fake_api_app = ModuleType("svgmaker_proxy.api.app")
    fake_api_app.create_app = lambda **_kwargs: SimpleNamespace(
        state=SimpleNamespace(
            mcp_server=SimpleNamespace(
                session_manager=SimpleNamespace(
                    run=lambda: _SessionRun(),
                )
            )
        )
    )
    fake_api_app.run_account_pool_refill_loop = _async_noop
    monkeypatch.setitem(sys.modules, "svgmaker_proxy.api.app", fake_api_app)

    stack_module = importlib.import_module("svgmaker_proxy.stack")

    monkeypatch.setattr(
        stack_module,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_bot_token="test-token",
            telegram_proxy_url="http://127.0.0.1:8080",
            log_level="INFO",
            api_host="127.0.0.1",
            api_port=8000,
        ),
    )
    monkeypatch.setattr(stack_module, "configure_logging", lambda _level: None)

    services = SimpleNamespace(database=SimpleNamespace(dispose=_async_noop))
    monkeypatch.setattr(stack_module, "build_services", lambda: services)
    monkeypatch.setattr(stack_module, "initialize_services", _async_noop)

    monkeypatch.setattr(stack_module.uvicorn, "Config", lambda **_kwargs: object())

    class FakeServer:
        def __init__(self, _config: object) -> None:
            self.should_exit = False

        async def serve(self) -> None:
            return None

    monkeypatch.setattr(stack_module.uvicorn, "Server", FakeServer)

    def fake_build_bot_session(proxy_url: str | None) -> object | None:
        captured["proxy_url"] = proxy_url
        return session_obj

    monkeypatch.setattr(stack_module, "build_bot_session", fake_build_bot_session)

    class FakeBot:
        def __init__(
            self,
            *,
            token: str,
            session: object | None = None,
            default: object | None = None,
        ) -> None:
            captured["bot_kwargs"] = {
                "token": token,
                "session": session,
                "default": default,
            }
            self.session = SimpleNamespace(close=self._close)

        async def _close(self) -> None:
            return None

    class FakeDispatcher:
        async def start_polling(self, _bot: FakeBot) -> None:
            return None

    monkeypatch.setattr(stack_module, "Bot", FakeBot)
    monkeypatch.setattr(stack_module, "Dispatcher", FakeDispatcher)
    monkeypatch.setattr(stack_module, "configure_dispatcher", _async_noop)
    monkeypatch.setattr(stack_module, "build_bot_service", lambda _services: object())

    await stack_module.run_stack()

    assert captured["proxy_url"] == "http://127.0.0.1:8080"
    assert captured["bot_kwargs"]["session"] is session_obj


class _SessionRun:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None
