from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from svgmaker_proxy import __version__
from svgmaker_proxy.bootstrap import ServiceContainer, build_services
from svgmaker_proxy.core.config import get_settings
from svgmaker_proxy.core.logging import configure_logging
from svgmaker_proxy.models.account import AccountRecord
from svgmaker_proxy.models.account_action import AccountActionRecord
from svgmaker_proxy.models.generation import SvgmakerGenerateRequest

logger = logging.getLogger(__name__)


class RegisterAccountRequest(BaseModel):
    email: str | None = None


class RefillAccountsRequest(BaseModel):
    target_active: int | None = Field(default=None, ge=1)


class AccountSummaryResponse(BaseModel):
    id: int
    email: str
    display_name: str
    status: str
    email_verified: bool
    has_complete_session: bool
    ready: bool
    credits_last_known: int | None
    failure_count: int
    created_at: str
    updated_at: str

    @classmethod
    def from_record(cls, record: AccountRecord) -> AccountSummaryResponse:
        return cls(
            id=record.id,
            email=str(record.email),
            display_name=record.display_name,
            status=record.status.value,
            email_verified=record.email_verified,
            has_complete_session=record.has_complete_svgmaker_session,
            ready=record.is_ready,
            credits_last_known=record.credits_last_known,
            failure_count=record.failure_count,
            created_at=record.created_at.isoformat(),
            updated_at=record.updated_at.isoformat(),
        )


class AccountActionResponse(BaseModel):
    id: int
    account_id: int
    action_type: str
    details: dict[str, Any]
    created_at: str

    @classmethod
    def from_record(cls, record: AccountActionRecord) -> AccountActionResponse:
        return cls(
            id=record.id,
            account_id=record.account_id,
            action_type=record.action_type.value,
            details=record.details,
            created_at=record.created_at.isoformat(),
        )


def get_services(request: Request) -> ServiceContainer:
    return request.app.state.services


async def initialize_services(services: ServiceContainer) -> None:
    await services.database.initialize()
    gmail_profile = await services.account_registrar.gmail_service.healthcheck()
    logger.info(
        "Gmail healthcheck passed for %s (messages=%s)",
        gmail_profile["email_address"],
        gmail_profile.get("messages_total"),
    )


async def run_account_pool_refill_loop(services: ServiceContainer) -> None:
    settings = get_settings()
    interval = max(5.0, settings.pool_refill_interval_seconds)
    while True:
        try:
            await services.account_pool.ensure_minimum_accounts()
        except Exception:  # noqa: BLE001
            logger.exception("Background account refill iteration failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    services = build_services()
    await initialize_services(services)
    app.state.services = services
    refill_task = asyncio.create_task(run_account_pool_refill_loop(services))
    try:
        yield
    finally:
        if not refill_task.done():
            refill_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await refill_task
        await services.database.dispose()


def create_app(
    *,
    services: ServiceContainer | None = None,
    manage_lifecycle: bool = True,
) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    lifespan_handler = lifespan if manage_lifecycle else None
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan_handler,
    )
    if services is not None:
        app.state.services = services

    @app.get("/health")
    async def healthcheck(request: Request) -> dict[str, Any]:
        services = get_services(request)
        return {
            "status": "ok",
            "environment": settings.app_env,
            "pool": await services.account_pool.get_pool_snapshot(),
        }

    @app.get("/metrics/summary")
    async def metrics_summary(request: Request) -> dict[str, Any]:
        services = get_services(request)
        recent_generations = await services.generation_repository.list_recent(limit=20)
        return {
            "pool": await services.account_pool.get_pool_snapshot(),
            "recent_generation_count": len(recent_generations),
        }

    @app.get("/accounts", response_model=list[AccountSummaryResponse])
    async def list_accounts(request: Request) -> list[AccountSummaryResponse]:
        services = get_services(request)
        accounts = await services.account_repository.list_all()
        return [AccountSummaryResponse.from_record(account) for account in accounts]

    @app.get("/accounts/ready", response_model=list[AccountSummaryResponse])
    async def list_ready_accounts(request: Request) -> list[AccountSummaryResponse]:
        services = get_services(request)
        accounts = await services.account_repository.list_ready()
        return [AccountSummaryResponse.from_record(account) for account in accounts]

    @app.get("/accounts/{account_id}/actions", response_model=list[AccountActionResponse])
    async def list_account_actions(
        account_id: int,
        request: Request,
    ) -> list[AccountActionResponse]:
        services = get_services(request)
        actions = await services.account_action_repository.list_for_account(account_id)
        return [AccountActionResponse.from_record(action) for action in actions]

    @app.post("/accounts/register")
    async def register_account(
        payload: RegisterAccountRequest,
        request: Request,
    ) -> dict[str, Any]:
        services = get_services(request)
        bundle = await services.account_registrar.register_account(email=payload.email)
        return {
            "account_id": bundle.account_id,
            "email": bundle.email,
            "display_name": bundle.display_name,
            "email_verified": bundle.email_verified,
            "credits_last_known": bundle.credits_last_known,
        }

    @app.post("/accounts/refill")
    async def refill_accounts(
        payload: RefillAccountsRequest,
        request: Request,
    ) -> dict[str, Any]:
        services = get_services(request)
        snapshot = await services.account_pool.refill_accounts(payload.target_active)
        return {"success": True, "pool": snapshot}

    @app.post("/generate")
    @app.post("/proxy/generate")
    async def proxy_generate(
        payload: SvgmakerGenerateRequest,
        request: Request,
    ) -> dict[str, Any]:
        services = get_services(request)
        result = await services.generation_proxy.generate(payload)
        return {
            "request_id": result.request_id,
            "account_id": result.account_id,
            "generation_id": result.generation_id,
            "svg_url": result.svg_url,
            "balance_before": result.balance_before,
            "balance_after": result.balance_after,
            "raw_payload": result.raw_payload,
        }

    @app.get("/generations/{request_id}")
    async def get_generation(request_id: int, request: Request) -> dict[str, Any]:
        services = get_services(request)
        generation = await services.generation_repository.get_by_id(request_id)
        if generation is None:
            return {"found": False}
        return {"found": True, "generation": generation.model_dump(mode="json")}

    return app


app = create_app()
