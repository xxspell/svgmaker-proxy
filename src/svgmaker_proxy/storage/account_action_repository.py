from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import Select, select

from svgmaker_proxy.models.account_action import (
    AccountActionCreate,
    AccountActionRecord,
    AccountActionType,
)
from svgmaker_proxy.storage.db import get_db_session
from svgmaker_proxy.storage.orm import AccountActionORM


class AccountActionRepository:
    async def create(self, payload: AccountActionCreate) -> AccountActionRecord:
        action = AccountActionORM(
            account_id=payload.account_id,
            action_type=payload.action_type.value,
            details=json.dumps(payload.details, ensure_ascii=False) if payload.details else None,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        async with get_db_session() as session:
            session.add(action)
            await session.flush()
            await session.refresh(action)
            return self._orm_to_model(action)

    async def list_for_account(
        self,
        account_id: int,
        limit: int = 100,
    ) -> list[AccountActionRecord]:
        statement = (
            select(AccountActionORM)
            .where(AccountActionORM.account_id == account_id)
            .order_by(AccountActionORM.id.desc())
            .limit(limit)
        )
        return await self._fetch_many(statement)

    async def has_action(
        self,
        account_id: int,
        action_type: AccountActionType,
    ) -> bool:
        statement = (
            select(AccountActionORM.id)
            .where(
                AccountActionORM.account_id == account_id,
                AccountActionORM.action_type == action_type.value,
            )
            .limit(1)
        )
        async with get_db_session() as session:
            result = await session.execute(statement)
            return result.scalar_one_or_none() is not None

    async def _fetch_many(
        self,
        statement: Select[tuple[AccountActionORM]],
    ) -> list[AccountActionRecord]:
        async with get_db_session() as session:
            result = await session.execute(statement)
            actions = result.scalars().all()
        return [self._orm_to_model(action) for action in actions]

    def _orm_to_model(self, action: AccountActionORM) -> AccountActionRecord:
        return AccountActionRecord(
            id=action.id,
            account_id=action.account_id,
            action_type=AccountActionType(action.action_type),
            details=self._load_details(action.details),
            created_at=self._restore_datetime(action.created_at),
        )

    def _load_details(self, raw: str | None) -> dict:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
        return value if isinstance(value, dict) else {"value": value}

    def _restore_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)
