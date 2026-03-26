from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import cycle

from svgmaker_proxy.clients.svgmaker_auth import SvgmakerSession
from svgmaker_proxy.core.config import Settings, get_settings
from svgmaker_proxy.models.account import AccountRecord, AccountStatus, AccountUpdate
from svgmaker_proxy.services.account_registrar import AccountRegistrarService
from svgmaker_proxy.storage.account_repository import AccountRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AccountLease:
    account_id: int
    email: str
    session: SvgmakerSession
    firebase_local_id: str | None = None
    firebase_id_token: str | None = None
    firebase_refresh_token: str | None = None


class AccountPoolService:
    def __init__(
        self,
        account_repository: AccountRepository,
        registrar: AccountRegistrarService,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.account_repository = account_repository
        self.registrar = registrar
        self._lock = asyncio.Lock()
        self._cycle_iter = cycle(())
        self._cycle_ids: list[int] = []

    async def list_active_accounts(self) -> list[AccountRecord]:
        return await self.account_repository.list_ready()

    async def acquire_account(
        self,
        exclude_account_ids: Iterable[int] | None = None,
    ) -> AccountLease:
        async with self._lock:
            excluded_ids = set(exclude_account_ids or [])
            active_accounts = await self._list_usable_accounts(excluded_ids)
            if not active_accounts:
                await self.ensure_minimum_accounts()
                active_accounts = await self._list_usable_accounts(excluded_ids)
            if not active_accounts:
                raise RuntimeError("No active accounts are available")

            await self._refresh_cycle(active_accounts)
            selected = self._select_next(active_accounts)
            session = self._to_session(selected)
            if not session:
                raise RuntimeError(
                    f"Account {selected.id} does not have complete SVGMaker session tokens"
                )
            return AccountLease(
                account_id=selected.id,
                email=selected.email,
                session=session,
                firebase_local_id=selected.firebase_local_id,
                firebase_id_token=selected.firebase_id_token,
                firebase_refresh_token=selected.firebase_refresh_token,
            )

    async def ensure_minimum_accounts(self) -> None:
        ready_count = await self.account_repository.count_ready()
        pending_count = await self.account_repository.count_by_status(AccountStatus.pending)
        verifying_count = await self.account_repository.count_by_status(
            AccountStatus.verifying_email
        )
        in_flight = pending_count + verifying_count
        desired = self.settings.target_ready_accounts
        minimum = self.settings.min_ready_accounts

        if ready_count >= minimum:
            return

        total_known = ready_count + in_flight
        missing = max(0, desired - total_known)
        capacity = max(0, self.settings.max_accounts_total - total_known)
        to_create = min(missing, capacity, self.settings.max_concurrent_registrations)

        if to_create <= 0:
            return

        logger.info(
            "Account pool below threshold: ready=%s minimum=%s target=%s creating=%s",
            ready_count,
            minimum,
            desired,
            to_create,
        )
        await asyncio.gather(*(self._safe_register() for _ in range(to_create)))

    async def refill_accounts(self, desired_active: int | None = None) -> dict[str, int]:
        target = desired_active or self.settings.target_ready_accounts
        ready_count = await self.account_repository.count_ready()
        pending_count = await self.account_repository.count_by_status(AccountStatus.pending)
        verifying_count = await self.account_repository.count_by_status(
            AccountStatus.verifying_email
        )

        in_flight = pending_count + verifying_count
        missing = max(0, target - (ready_count + in_flight))
        capacity = max(0, self.settings.max_accounts_total - (ready_count + in_flight))
        to_create = min(missing, capacity, self.settings.max_concurrent_registrations)
        if to_create > 0:
            await asyncio.gather(*(self._safe_register() for _ in range(to_create)))
        return await self.get_pool_snapshot()

    async def get_pool_snapshot(self) -> dict[str, int]:
        ready = await self.account_repository.count_ready()
        active = await self.account_repository.count_by_status(AccountStatus.active)
        pending = await self.account_repository.count_by_status(AccountStatus.pending)
        verifying = await self.account_repository.count_by_status(AccountStatus.verifying_email)
        failed = await self.account_repository.count_by_status(AccountStatus.failed)
        blocked = await self.account_repository.count_by_status(AccountStatus.blocked)
        cooling_down = await self.account_repository.count_by_status(AccountStatus.cooling_down)
        return {
            "ready": ready,
            "active": active,
            "pending": pending,
            "verifying_email": verifying,
            "failed": failed,
            "blocked": blocked,
            "cooling_down": cooling_down,
        }

    async def mark_success(self, account_id: int) -> None:
        now = self._utcnow()
        await self.account_repository.update(
            account_id,
            AccountUpdate(
                status=AccountStatus.active,
                failure_count=0,
                last_generation_at=now,
                last_checked_at=now,
            ),
        )

    async def mark_failure(self, account_id: int, error_message: str) -> AccountStatus:
        account = await self.account_repository.get_by_id(account_id)
        if not account:
            raise RuntimeError(f"Account {account_id} was not found")

        next_failures = account.failure_count + 1
        error_lower = error_message.lower()
        next_status = AccountStatus.active
        if "429" in error_lower or "rate" in error_lower:
            next_status = AccountStatus.cooling_down
        elif "block" in error_lower or "suspend" in error_lower:
            next_status = AccountStatus.blocked
        elif next_failures >= self.settings.account_error_limit:
            next_status = AccountStatus.failed

        await self.account_repository.update(
            account_id,
            AccountUpdate(
                status=next_status,
                failure_count=next_failures,
                last_checked_at=self._utcnow(),
            ),
        )
        return next_status

    async def _safe_register(self) -> None:
        try:
            await self.registrar.register_account()
        except Exception:  # noqa: BLE001
            logger.exception("Automatic account registration attempt failed")

    async def _refresh_cycle(self, active_accounts: list[AccountRecord]) -> None:
        ids = [item.id for item in active_accounts]
        if ids != self._cycle_ids:
            self._cycle_ids = ids
            self._cycle_iter = cycle(ids)

    async def _list_usable_accounts(
        self,
        exclude_account_ids: set[int] | None = None,
    ) -> list[AccountRecord]:
        active_accounts = await self.account_repository.list_ready()
        excluded_ids = exclude_account_ids or set()
        return [
            account
            for account in active_accounts
            if account.id not in excluded_ids
            and account.failure_count < self.settings.account_error_limit
            and account.credits_last_known != 0
        ]

    def _select_next(self, active_accounts: list[AccountRecord]) -> AccountRecord:
        by_id = {item.id: item for item in active_accounts}
        for _ in range(len(active_accounts)):
            selected_id = next(self._cycle_iter)
            account = by_id.get(selected_id)
            if account:
                return account
        return active_accounts[0]

    def _to_session(self, account: AccountRecord) -> SvgmakerSession | None:
        if not (
            account.svgmaker_auth_token_id
            and account.svgmaker_auth_token_refresh
            and account.svgmaker_auth_token_sig
        ):
            return None
        return SvgmakerSession(
            auth_token_id=account.svgmaker_auth_token_id,
            auth_token_refresh=account.svgmaker_auth_token_refresh,
            auth_token_sig=account.svgmaker_auth_token_sig,
            bearer_token=account.svgmaker_auth_token_id,
        )

    def _utcnow(self) -> datetime:
        return datetime.now(UTC)
