from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Select, func, select

from svgmaker_proxy.models.account import AccountCreate, AccountRecord, AccountStatus, AccountUpdate
from svgmaker_proxy.storage.db import get_db_session
from svgmaker_proxy.storage.orm import AccountORM


class AccountRepository:
    async def create(self, payload: AccountCreate) -> AccountRecord:
        now = datetime.now(UTC).replace(tzinfo=None)
        account = AccountORM(
            email=str(payload.email),
            password=payload.password,
            display_name=payload.display_name,
            status=payload.status.value,
            email_verified=payload.email_verified,
            firebase_local_id=payload.firebase_local_id,
            firebase_id_token=payload.firebase_id_token,
            firebase_refresh_token=payload.firebase_refresh_token,
            svgmaker_auth_token_id=payload.svgmaker_auth_token_id,
            svgmaker_auth_token_refresh=payload.svgmaker_auth_token_refresh,
            svgmaker_auth_token_sig=payload.svgmaker_auth_token_sig,
            credits_last_known=payload.credits_last_known,
            last_generation_at=self._normalize_datetime(payload.last_generation_at),
            last_refreshed_at=self._normalize_datetime(payload.last_refreshed_at),
            last_checked_at=self._normalize_datetime(payload.last_checked_at),
            failure_count=payload.failure_count,
            created_at=now,
            updated_at=now,
        )

        async with get_db_session() as session:
            session.add(account)
            await session.flush()
            await session.refresh(account)
            return self._orm_to_model(account)

    async def get_by_id(self, account_id: int) -> AccountRecord | None:
        statement = select(AccountORM).where(AccountORM.id == account_id)
        return await self._fetch_one(statement)

    async def get_by_email(self, email: str) -> AccountRecord | None:
        statement = select(AccountORM).where(AccountORM.email == email)
        return await self._fetch_one(statement)

    async def list_by_status(self, status: AccountStatus) -> list[AccountRecord]:
        statement = (
            select(AccountORM)
            .where(AccountORM.status == status.value)
            .order_by(AccountORM.id.asc())
        )
        return await self._fetch_many(statement)

    async def list_all(self) -> list[AccountRecord]:
        statement = select(AccountORM).order_by(AccountORM.id.asc())
        return await self._fetch_many(statement)

    async def list_ready(self) -> list[AccountRecord]:
        statement = (
            select(AccountORM)
            .where(
                AccountORM.status == AccountStatus.active.value,
                AccountORM.email_verified.is_(True),
                AccountORM.svgmaker_auth_token_id.is_not(None),
                AccountORM.svgmaker_auth_token_refresh.is_not(None),
                AccountORM.svgmaker_auth_token_sig.is_not(None),
            )
            .order_by(AccountORM.id.asc())
        )
        return await self._fetch_many(statement)

    async def count_by_status(self, status: AccountStatus) -> int:
        statement = select(func.count(AccountORM.id)).where(AccountORM.status == status.value)
        async with get_db_session() as session:
            result = await session.execute(statement)
            total = result.scalar_one()
        return int(total)

    async def count_ready(self) -> int:
        statement = select(func.count(AccountORM.id)).where(
            AccountORM.status == AccountStatus.active.value,
            AccountORM.email_verified.is_(True),
            AccountORM.svgmaker_auth_token_id.is_not(None),
            AccountORM.svgmaker_auth_token_refresh.is_not(None),
            AccountORM.svgmaker_auth_token_sig.is_not(None),
        )
        async with get_db_session() as session:
            result = await session.execute(statement)
            total = result.scalar_one()
        return int(total)

    async def update(self, account_id: int, payload: AccountUpdate) -> AccountRecord | None:
        values = payload.model_dump(exclude_none=True)
        if not values:
            return await self.get_by_id(account_id)

        async with get_db_session() as session:
            account = await session.get(AccountORM, account_id)
            if account is None:
                return None

            for key, value in values.items():
                if isinstance(value, AccountStatus):
                    value = value.value
                elif isinstance(value, datetime):
                    value = self._normalize_datetime(value)
                setattr(account, key, value)

            account.updated_at = datetime.now(UTC).replace(tzinfo=None)
            await session.flush()
            await session.refresh(account)
            return self._orm_to_model(account)

    async def _fetch_one(self, statement: Select[tuple[AccountORM]]) -> AccountRecord | None:
        async with get_db_session() as session:
            result = await session.execute(statement)
            account = result.scalar_one_or_none()
        return self._orm_to_model(account) if account is not None else None

    async def _fetch_many(self, statement: Select[tuple[AccountORM]]) -> list[AccountRecord]:
        async with get_db_session() as session:
            result = await session.execute(statement)
            accounts = result.scalars().all()
        return [self._orm_to_model(account) for account in accounts]

    def _orm_to_model(self, account: AccountORM) -> AccountRecord:
        return AccountRecord(
            id=account.id,
            email=account.email,
            password=account.password,
            display_name=account.display_name,
            status=AccountStatus(account.status),
            email_verified=account.email_verified,
            firebase_local_id=account.firebase_local_id,
            firebase_id_token=account.firebase_id_token,
            firebase_refresh_token=account.firebase_refresh_token,
            svgmaker_auth_token_id=account.svgmaker_auth_token_id,
            svgmaker_auth_token_refresh=account.svgmaker_auth_token_refresh,
            svgmaker_auth_token_sig=account.svgmaker_auth_token_sig,
            credits_last_known=account.credits_last_known,
            last_generation_at=self._restore_datetime(account.last_generation_at),
            last_refreshed_at=self._restore_datetime(account.last_refreshed_at),
            last_checked_at=self._restore_datetime(account.last_checked_at),
            failure_count=account.failure_count,
            created_at=self._restore_datetime(account.created_at),
            updated_at=self._restore_datetime(account.updated_at),
        )

    def _normalize_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    def _restore_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)
