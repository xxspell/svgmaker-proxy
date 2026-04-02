from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="svgmaker-proxy", alias="APP_NAME")
    app_env: Literal["dev", "test", "prod"] = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    api_host: str = Field(default="0.0.0.0", alias="SVGM_PROXY_HOST")
    api_port: int = Field(default=8000, alias="SVGM_PROXY_PORT")
    mcp_mount_path: str = Field(default="/mcp", alias="SVGM_PROXY_MCP_PATH")

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@postgres:5432/svgmaker_proxy",
        alias="DATABASE_URL",
    )

    svgmaker_base_url: str = Field(default="https://svgmaker.io", alias="SVGM_BASE_URL")
    firebase_api_key: str = Field(
        default="AIzaSyCrczE7Kslzm7pgRO8UgNunu_XLgzruxxI",
        alias="FIREBASE_API_KEY",
    )
    firebase_project_id: str = Field(default="svgmaker-fun", alias="FIREBASE_PROJECT_ID")
    firebase_gmpid: str = Field(
        default="1:574578265104:web:05cdd0d253217108a88e95",
        alias="FIREBASE_GMPID",
    )
    firebase_client_version: str = Field(
        default="Chrome/JsCore/12.9.0/FirebaseCore-web",
        alias="FIREBASE_CLIENT_VERSION",
    )

    request_timeout_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices("SVGM_PROXY_REQUEST_TIMEOUT", "SVGM_REQUEST_TIMEOUT"),
    )
    generation_timeout_seconds: float = Field(
        default=300.0,
        validation_alias=AliasChoices("SVGM_PROXY_GENERATE_TIMEOUT", "SVGM_GENERATE_TIMEOUT"),
    )

    min_ready_accounts: int = Field(
        default=3,
        validation_alias=AliasChoices("SVGM_PROXY_MIN_READY_ACCOUNTS", "SVGM_MIN_READY_ACCOUNTS"),
    )
    target_ready_accounts: int = Field(
        default=5,
        validation_alias=AliasChoices(
            "SVGM_PROXY_TARGET_READY_ACCOUNTS",
            "SVGM_TARGET_READY_ACCOUNTS",
        ),
    )
    max_accounts_total: int = Field(
        default=50,
        validation_alias=AliasChoices("SVGM_PROXY_MAX_ACCOUNTS_TOTAL", "SVGM_MAX_ACCOUNTS_TOTAL"),
    )
    max_concurrent_registrations: int = Field(
        default=2,
        validation_alias=AliasChoices(
            "SVGM_PROXY_MAX_CONCURRENT_REGISTRATIONS",
            "SVGM_MAX_CONCURRENT_REGISTRATIONS",
        ),
    )
    account_error_limit: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "SVGM_PROXY_ACCOUNT_ERROR_LIMIT",
            "SVGM_ACCOUNT_ERROR_LIMIT",
        ),
    )
    account_selection_strategy: Literal["round_robin"] = Field(
        default="round_robin",
        alias="SVGM_PROXY_ACCOUNT_SELECTION_STRATEGY",
    )
    pool_refill_interval_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices(
            "SVGM_PROXY_POOL_REFILL_INTERVAL_SECONDS",
            "SVGM_POOL_REFILL_INTERVAL_SECONDS",
        ),
    )
    generation_retry_attempts: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "SVGM_PROXY_GENERATION_RETRY_ATTEMPTS",
            "SVGM_GENERATION_RETRY_ATTEMPTS",
        ),
    )
    generate_min_credits: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "SVGM_PROXY_GENERATE_MIN_CREDITS",
            "SVGM_GENERATE_MIN_CREDITS",
        ),
    )
    edit_min_credits: int = Field(
        default=5,
        validation_alias=AliasChoices(
            "SVGM_PROXY_EDIT_MIN_CREDITS",
            "SVGM_EDIT_MIN_CREDITS",
        ),
    )
    account_acquire_wait_seconds: float = Field(
        default=180.0,
        validation_alias=AliasChoices(
            "SVGM_PROXY_ACCOUNT_ACQUIRE_WAIT_SECONDS",
            "SVGM_ACCOUNT_ACQUIRE_WAIT_SECONDS",
        ),
    )
    unknown_balance_refresh_interval_seconds: float = Field(
        default=3600.0,
        validation_alias=AliasChoices(
            "SVGM_PROXY_UNKNOWN_BALANCE_REFRESH_INTERVAL_SECONDS",
            "SVGM_UNKNOWN_BALANCE_REFRESH_INTERVAL_SECONDS",
        ),
    )
    low_balance_refresh_interval_seconds: float = Field(
        default=90000.0,
        validation_alias=AliasChoices(
            "SVGM_PROXY_LOW_BALANCE_REFRESH_INTERVAL_SECONDS",
            "SVGM_LOW_BALANCE_REFRESH_INTERVAL_SECONDS",
        ),
    )
    known_balance_refresh_interval_seconds: float = Field(
        default=86400.0,
        validation_alias=AliasChoices(
            "SVGM_PROXY_KNOWN_BALANCE_REFRESH_INTERVAL_SECONDS",
            "SVGM_KNOWN_BALANCE_REFRESH_INTERVAL_SECONDS",
        ),
    )
    max_balance_refresh_per_cycle: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "SVGM_PROXY_MAX_BALANCE_REFRESH_PER_CYCLE",
            "SVGM_MAX_BALANCE_REFRESH_PER_CYCLE",
        ),
    )
    account_acquire_poll_interval_seconds: float = Field(
        default=2.0,
        validation_alias=AliasChoices(
            "SVGM_PROXY_ACCOUNT_ACQUIRE_POLL_INTERVAL_SECONDS",
            "SVGM_ACCOUNT_ACQUIRE_POLL_INTERVAL_SECONDS",
        ),
    )
    zero_balance_refresh_interval_seconds: float = Field(
        default=90000.0,
        validation_alias=AliasChoices(
            "SVGM_PROXY_ZERO_BALANCE_REFRESH_INTERVAL_SECONDS",
            "SVGM_ZERO_BALANCE_REFRESH_INTERVAL_SECONDS",
            "SVGM_PROXY_LOW_BALANCE_REFRESH_INTERVAL_SECONDS",
            "SVGM_LOW_BALANCE_REFRESH_INTERVAL_SECONDS",
        ),
    )
    account_acquire_poll_interval_seconds: float = Field(
        default=2.0,
        validation_alias=AliasChoices(
            "SVGM_PROXY_ACCOUNT_ACQUIRE_POLL_INTERVAL_SECONDS",
            "SVGM_ACCOUNT_ACQUIRE_POLL_INTERVAL_SECONDS",
        ),
    )
    zero_balance_refresh_interval_seconds: float = Field(
        default=90000.0,
        validation_alias=AliasChoices(
            "SVGM_PROXY_ZERO_BALANCE_REFRESH_INTERVAL_SECONDS",
            "SVGM_ZERO_BALANCE_REFRESH_INTERVAL_SECONDS",
        ),
    )

    generate_quality_default: str = Field(default="high", alias="SVGM_DEFAULT_QUALITY")
    generate_aspect_ratio_default: str = Field(
        default="auto",
        alias="SVGM_DEFAULT_ASPECT_RATIO",
    )
    generate_background_default: str = Field(
        default="auto",
        alias="SVGM_DEFAULT_BACKGROUND",
    )

    recaptcha_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("SVGM_PROXY_RECAPTCHA_ENABLED", "SVGM_RECAPTCHA_ENABLED"),
    )
    recaptcha_site_key: str | None = Field(default=None, alias="SVGM_RECAPTCHA_SITE_KEY")
    recaptcha_secret: str | None = Field(default=None, alias="SVGM_RECAPTCHA_SECRET")

    gmail_client_id: str | None = Field(default=None, alias="GMAIL_CLIENT_ID")
    gmail_client_secret: str | None = Field(default=None, alias="GMAIL_CLIENT_SECRET")
    gmail_refresh_token: str | None = Field(default=None, alias="GMAIL_REFRESH_TOKEN")
    gmail_access_token: str | None = Field(default=None, alias="GMAIL_ACCESS_TOKEN")

    email_domains: str = Field(
        default="",
        validation_alias=AliasChoices("SVGM_PROXY_EMAIL_DOMAINS", "EMAIL_DOMAINS"),
    )
    email_inbox_query_label: str | None = Field(default=None, alias="EMAIL_INBOX_QUERY_LABEL")
    email_poll_timeout_seconds: float = Field(
        default=180.0,
        validation_alias=AliasChoices(
            "SVGM_PROXY_EMAIL_TIMEOUT_SECONDS",
            "EMAIL_POLL_TIMEOUT",
        ),
    )
    email_poll_interval_seconds: float = Field(
        default=5.0,
        validation_alias=AliasChoices(
            "SVGM_PROXY_EMAIL_POLL_INTERVAL_SECONDS",
            "EMAIL_POLL_INTERVAL",
        ),
    )
    verification_email_attempt_timeout_seconds: float = Field(
        default=100.0,
        validation_alias=AliasChoices(
            "SVGM_PROXY_VERIFY_EMAIL_ATTEMPT_TIMEOUT_SECONDS",
            "VERIFY_EMAIL_ATTEMPT_TIMEOUT_SECONDS",
        ),
    )
    verification_email_max_attempts: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "SVGM_PROXY_VERIFY_EMAIL_MAX_ATTEMPTS",
            "VERIFY_EMAIL_MAX_ATTEMPTS",
        ),
    )

    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_initial_generations: int = Field(default=3, alias="TELEGRAM_INITIAL_GENERATIONS")
    telegram_daily_generations: int = Field(default=1, alias="TELEGRAM_DAILY_GENERATIONS")
    telegram_welcome_generate_button: str = Field(
        default="Generate image",
        alias="TELEGRAM_BUTTON_GENERATE",
    )

    svgmaker_origin: str = Field(default="https://svgmaker.io", alias="SVGM_ORIGIN")
    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        ),
        alias="SVGM_USER_AGENT",
    )
    accept_language: str = Field(default="ru-RU,ru;q=0.9", alias="SVGM_ACCEPT_LANGUAGE")
    timezone_header: str = Field(default="Asia/Yekaterinburg", alias="SVGM_TIMEZONE")
    user_country_header: str = Field(default="Bulgaria", alias="SVGM_USER_COUNTRY")

    @property
    def email_domains_list(self) -> list[str]:
        return [item.strip() for item in self.email_domains.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
