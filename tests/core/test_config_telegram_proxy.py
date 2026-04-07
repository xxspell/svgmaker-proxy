from svgmaker_proxy.core.config import Settings


def test_telegram_proxy_url_from_env_name() -> None:
    settings = Settings(TELEGRAM_PROXY_URL="http://127.0.0.1:8080", _env_file=None)
    assert settings.telegram_proxy_url == "http://127.0.0.1:8080"


def test_telegram_proxy_url_defaults_to_none(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_PROXY_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.telegram_proxy_url is None
