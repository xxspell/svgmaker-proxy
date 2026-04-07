from __future__ import annotations

from types import SimpleNamespace

import pytest

from svgmaker_proxy.telegram import app as app_module


@pytest.mark.asyncio
async def test_run_bot_uses_proxy_session(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    session_obj = object()

    monkeypatch.setattr(
        app_module,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_bot_token="test-token",
            telegram_proxy_url="http://127.0.0.1:8080",
            log_level="INFO",
        ),
    )
    monkeypatch.setattr(app_module, "configure_logging", lambda _level: None)

    def fake_build_bot_session(proxy_url: str | None) -> object | None:
        captured["proxy_url"] = proxy_url
        return session_obj

    monkeypatch.setattr(app_module, "build_bot_session", fake_build_bot_session)

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

    async def fake_configure_dispatcher(_dp: FakeDispatcher, _bot_service: object) -> None:
        return None

    monkeypatch.setattr(app_module, "Bot", FakeBot)
    monkeypatch.setattr(app_module, "Dispatcher", FakeDispatcher)
    monkeypatch.setattr(app_module, "configure_dispatcher", fake_configure_dispatcher)
    monkeypatch.setattr(app_module, "build_bot_service", lambda _services: object())

    await app_module.run_bot(services=object(), initialize=False)

    assert captured["proxy_url"] == "http://127.0.0.1:8080"
    assert captured["bot_kwargs"]["session"] is session_obj
