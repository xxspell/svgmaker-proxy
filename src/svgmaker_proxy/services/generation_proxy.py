from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from svgmaker_proxy.clients.firebase_identity import FirebaseIdentityClient, FirebaseIdentityError
from svgmaker_proxy.clients.svgmaker_generation import SvgmakerGenerationClient
from svgmaker_proxy.core.config import Settings, get_settings
from svgmaker_proxy.models.account import AccountUpdate
from svgmaker_proxy.models.account_action import AccountActionType
from svgmaker_proxy.models.generation import (
    GenerationRequestCreate,
    GenerationRequestUpdate,
    GenerationStatus,
    SvgmakerGenerateRequest,
)
from svgmaker_proxy.services.account_action_logger import AccountActionLogger
from svgmaker_proxy.services.account_pool import AccountLease, AccountPoolService
from svgmaker_proxy.storage.account_repository import AccountRepository
from svgmaker_proxy.storage.generation_repository import GenerationRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProxiedGenerationResult:
    request_id: int
    account_id: int
    generation_id: str | None
    svg_url: str | None
    balance_before: int | None
    balance_after: int | None
    raw_payload: dict[str, Any]


class GenerationProxyService:
    def __init__(
        self,
        account_pool: AccountPoolService,
        account_repository: AccountRepository,
        generation_repository: GenerationRepository,
        generation_client: SvgmakerGenerationClient,
        firebase_client: FirebaseIdentityClient,
        action_logger: AccountActionLogger | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.account_pool = account_pool
        self.account_repository = account_repository
        self.generation_repository = generation_repository
        self.generation_client = generation_client
        self.firebase_client = firebase_client
        self.action_logger = action_logger

    async def generate(self, request: SvgmakerGenerateRequest) -> ProxiedGenerationResult:
        await self.account_pool.ensure_minimum_accounts()
        record = None
        attempted_account_ids: set[int] = set()
        last_error: Exception | None = None

        for attempt in range(1, self.settings.generation_retry_attempts + 1):
            try:
                lease = await self.account_pool.acquire_account(
                    exclude_account_ids=attempted_account_ids
                )
            except Exception:
                if last_error is not None:
                    break
                raise
            attempted_account_ids.add(lease.account_id)
            logger.info(
                "Proxy generation started account_id=%s email=%s attempt=%s/%s prompt=%r "
                "quality=%s aspect_ratio=%s background=%s",
                lease.account_id,
                lease.email,
                attempt,
                self.settings.generation_retry_attempts,
                request.prompt,
                request.quality,
                request.aspect_ratio,
                request.background,
            )
            await self._log_action(
                lease.account_id,
                AccountActionType.generation_started,
                prompt=request.prompt,
                quality=request.quality,
                aspect_ratio=request.aspect_ratio,
                background=request.background,
                attempt=attempt,
            )

            if record is None:
                record = await self.generation_repository.create(
                    GenerationRequestCreate(
                        account_id=lease.account_id,
                        prompt=request.prompt,
                        quality=request.quality,
                        aspect_ratio=request.aspect_ratio,
                        background=request.background,
                        status=GenerationStatus.running,
                    )
                )
            elif record.account_id != lease.account_id:
                record = await self.generation_repository.update(
                    record.id,
                    GenerationRequestUpdate(
                        account_id=lease.account_id,
                        status=GenerationStatus.running,
                        error_message=None,
                    ),
                ) or record

            result = await self._run_generation_attempt(
                lease=lease,
                request=request,
                record_id=record.id,
            )
            if isinstance(result, ProxiedGenerationResult):
                return result

            last_error = result
            if not self._should_retry_with_another_account(result):
                break

            await self.account_repository.update(
                lease.account_id,
                AccountUpdate(
                    credits_last_known=0,
                    last_checked_at=self._utcnow(),
                ),
            )
            await self._log_action(
                lease.account_id,
                AccountActionType.generation_failed,
                request_id=record.id,
                error=str(result),
                attempt=attempt,
                retrying=True,
                retry_reason="payment_required",
            )
            logger.warning(
                "Generation attempt hit exhausted balance account_id=%s request_id=%s "
                "attempt=%s/%s, retrying with another account",
                lease.account_id,
                record.id,
                attempt,
                self.settings.generation_retry_attempts,
            )

        if record is None or last_error is None:
            raise RuntimeError("Generation failed before any attempt was executed")

        await self.generation_repository.update(
            record.id,
            GenerationRequestUpdate(
                status=GenerationStatus.failed,
                error_message=str(last_error),
            ),
        )
        raise last_error

    async def _run_generation_attempt(
        self,
        *,
        lease: AccountLease,
        request: SvgmakerGenerateRequest,
        record_id: int,
    ) -> ProxiedGenerationResult | Exception:
        balance_before_task = asyncio.create_task(
            self._capture_balance_snapshot(lease=lease, phase="before", request_id=record_id)
        )

        try:
            payload = await self.generation_client.generate_to_completion(lease.session, request)
        except Exception as exc:
            balance_before = await self._await_optional_task(balance_before_task)
            if self._should_retry_with_another_account(exc):
                logger.warning(
                    "Proxy generation received retryable payment error "
                    "account_id=%s request_id=%s: %s",
                    lease.account_id,
                    record_id,
                    exc,
                )
                return exc
            logger.exception(
                "Proxy generation failed account_id=%s request_id=%s",
                lease.account_id,
                record_id,
            )
            await self.generation_repository.update(
                record_id,
                GenerationRequestUpdate(
                    status=GenerationStatus.failed,
                    error_message=str(exc),
                ),
            )
            await self.account_pool.mark_failure(lease.account_id, str(exc))
            await self._log_action(
                lease.account_id,
                AccountActionType.generation_failed,
                request_id=record_id,
                error=str(exc),
                balance_before=balance_before,
            )
            return exc

        balance_before = await self._await_optional_task(balance_before_task)
        generation_id = self._as_optional_str(payload.get("generationId"))
        svg_url = self._first_svg_url(payload)
        credit_cost = self._as_optional_int(payload.get("creditCost"))
        balance_after = await self._capture_balance_snapshot(
            lease=lease,
            phase="after",
            request_id=record_id,
            generation_id=generation_id,
        )

        await self.generation_repository.update(
            record_id,
            GenerationRequestUpdate(
                status=GenerationStatus.completed,
                external_generation_id=generation_id,
                svg_url=svg_url,
                credit_cost=credit_cost,
                error_message=None,
            ),
        )
        await self.account_pool.mark_success(lease.account_id)
        logger.info(
            "Proxy generation completed account_id=%s request_id=%s "
            "generation_id=%s credit_cost=%s svg_url=%s balance_before=%s balance_after=%s",
            lease.account_id,
            record_id,
            generation_id,
            credit_cost,
            svg_url,
            balance_before,
            balance_after,
        )
        await self._log_action(
            lease.account_id,
            AccountActionType.generation_completed,
            request_id=record_id,
            generation_id=generation_id,
            credit_cost=credit_cost,
            svg_url=svg_url,
            balance_before=balance_before,
            balance_after=balance_after,
        )

        return ProxiedGenerationResult(
            request_id=record_id,
            account_id=lease.account_id,
            generation_id=generation_id,
            svg_url=svg_url,
            balance_before=balance_before,
            balance_after=balance_after,
            raw_payload=payload,
        )

    def _should_retry_with_another_account(self, exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code == 402
        message = str(exc).lower()
        return "402" in message or "payment required" in message

    def _first_svg_url(self, payload: dict[str, Any]) -> str | None:
        direct = self._as_optional_str(payload.get("svgUrl"))
        if direct:
            return direct
        urls = payload.get("allSvgUrls")
        if isinstance(urls, list) and urls:
            first = urls[0]
            if isinstance(first, str) and first:
                return first
        return None

    def _as_optional_str(self, value: Any) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None

    def _as_optional_int(self, value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    async def _capture_balance_snapshot(
        self,
        *,
        lease: AccountLease,
        phase: str,
        request_id: int,
        generation_id: str | None = None,
    ) -> int | None:
        if not lease.firebase_local_id:
            return None

        id_token = lease.firebase_id_token
        refresh_token = lease.firebase_refresh_token
        if not id_token and refresh_token:
            refreshed = await self.firebase_client.refresh(refresh_token)
            id_token = refreshed.id_token
            lease.firebase_id_token = refreshed.id_token
            lease.firebase_refresh_token = refreshed.refresh_token
            await self.account_repository.update(
                lease.account_id,
                AccountUpdate(
                    firebase_id_token=refreshed.id_token,
                    firebase_refresh_token=refreshed.refresh_token,
                    last_refreshed_at=self._utcnow(),
                ),
            )
        if not id_token:
            return None

        try:
            document = await self.firebase_client.get_user_document(
                id_token=id_token,
                firebase_local_id=lease.firebase_local_id,
            )
        except FirebaseIdentityError as exc:
            if refresh_token and "request failed" in str(exc).lower():
                refreshed = await self.firebase_client.refresh(refresh_token)
                lease.firebase_id_token = refreshed.id_token
                lease.firebase_refresh_token = refreshed.refresh_token
                await self.account_repository.update(
                    lease.account_id,
                    AccountUpdate(
                        firebase_id_token=refreshed.id_token,
                        firebase_refresh_token=refreshed.refresh_token,
                        last_refreshed_at=self._utcnow(),
                    ),
                )
                document = await self.firebase_client.get_user_document(
                    id_token=refreshed.id_token,
                    firebase_local_id=lease.firebase_local_id,
                )
            else:
                logger.warning(
                    "Failed to fetch balance snapshot account_id=%s phase=%s: %s",
                    lease.account_id,
                    phase,
                    exc,
                )
                return None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to fetch balance snapshot account_id=%s phase=%s: %s",
                lease.account_id,
                phase,
                exc,
            )
            return None

        credits = document.fields.get("credits")
        balance = credits if isinstance(credits, int) else None
        if balance is not None:
            await self.account_repository.update(
                lease.account_id,
                AccountUpdate(
                    credits_last_known=balance,
                    last_checked_at=self._utcnow(),
                ),
            )
        await self._log_action(
            lease.account_id,
            AccountActionType.generation_balance_snapshot,
            phase=phase,
            request_id=request_id,
            generation_id=generation_id,
            credits=balance,
            path=document.path,
        )
        return balance

    async def _await_optional_task(self, task: asyncio.Task[int | None]) -> int | None:
        try:
            return await task
        except Exception as exc:  # noqa: BLE001
            logger.warning("Balance snapshot task failed: %s", exc)
            return None

    def _utcnow(self) -> datetime:
        return datetime.now(UTC)

    async def _log_action(
        self,
        account_id: int,
        action_type: AccountActionType,
        **details: Any,
    ) -> None:
        if self.action_logger is None:
            return
        await self.action_logger.log(account_id, action_type, **details)
