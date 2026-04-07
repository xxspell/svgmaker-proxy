from svgmaker_proxy.telegram import session as session_module
from svgmaker_proxy.telegram.session import build_bot_session


def test_build_bot_session_without_proxy_returns_none() -> None:
    assert build_bot_session(None) is None


def test_build_bot_session_with_proxy_returns_aiohttp_session(monkeypatch) -> None:
    class FakeAiohttpSession:
        def __init__(self, *, proxy: str | None = None) -> None:
            self.proxy = proxy

    monkeypatch.setattr(session_module, "AiohttpSession", FakeAiohttpSession)

    session = build_bot_session("http://127.0.0.1:8080")

    assert isinstance(session, FakeAiohttpSession)
    assert session.proxy == "http://127.0.0.1:8080"


def test_build_bot_session_with_auth_proxy_url(monkeypatch) -> None:
    class FakeAiohttpSession:
        def __init__(self, *, proxy: str | None = None) -> None:
            self.proxy = proxy

    monkeypatch.setattr(session_module, "AiohttpSession", FakeAiohttpSession)

    session = build_bot_session("http://user:pass@127.0.0.1:8080")

    assert isinstance(session, FakeAiohttpSession)
    assert session.proxy == "http://user:pass@127.0.0.1:8080"
