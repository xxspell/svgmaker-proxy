from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select

from svgmaker_proxy.models.telegram import (
    TelegramUserCreate,
    TelegramUserRecord,
    TelegramUserUpdate,
)
from svgmaker_proxy.storage.db import get_db_session
from svgmaker_proxy.storage.orm import TelegramUserORM


class TelegramUserRepository:
    async def create(self, payload: TelegramUserCreate) -> TelegramUserRecord:
        now = datetime.now(UTC).replace(tzinfo=None)
        user = TelegramUserORM(
            telegram_user_id=payload.telegram_user_id,
            username=payload.username,
            first_name=payload.first_name,
            last_name=payload.last_name,
            display_name=payload.display_name,
            quota_remaining=payload.quota_remaining,
            initial_grant_applied=payload.initial_grant_applied,
            last_daily_grant_on=payload.last_daily_grant_on,
            last_generation_at=self._normalize_datetime(payload.last_generation_at),
            started_with_code=payload.started_with_code,
            is_unlimited=payload.is_unlimited,
            created_at=now,
            updated_at=now,
        )
        async with get_db_session() as session:
            session.add(user)
            await session.flush()
            await session.refresh(user)
            return self._orm_to_model(user)

    async def get_by_telegram_user_id(self, telegram_user_id: int) -> TelegramUserRecord | None:
        statement = select(TelegramUserORM).where(
            TelegramUserORM.telegram_user_id == telegram_user_id
        )
        async with get_db_session() as session:
            result = await session.execute(statement)
            user = result.scalar_one_or_none()
        return self._orm_to_model(user) if user is not None else None

    async def update(
        self,
        telegram_user_id: int,
        payload: TelegramUserUpdate,
    ) -> TelegramUserRecord | None:
        values = payload.model_dump(exclude_none=True)
        async with get_db_session() as session:
            statement = select(TelegramUserORM).where(
                TelegramUserORM.telegram_user_id == telegram_user_id
            )
            result = await session.execute(statement)
            user = result.scalar_one_or_none()
            if user is None:
                return None

            for key, value in values.items():
                if isinstance(value, datetime):
                    value = self._normalize_datetime(value)
                setattr(user, key, value)

            user.updated_at = datetime.now(UTC).replace(tzinfo=None)
            await session.flush()
            await session.refresh(user)
            return self._orm_to_model(user)

    def _orm_to_model(self, user: TelegramUserORM) -> TelegramUserRecord:
        return TelegramUserRecord(
            id=user.id,
            telegram_user_id=user.telegram_user_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            display_name=user.display_name,
            quota_remaining=user.quota_remaining,
            initial_grant_applied=user.initial_grant_applied,
            last_daily_grant_on=self._restore_date(user.last_daily_grant_on),
            last_generation_at=self._restore_datetime(user.last_generation_at),
            started_with_code=user.started_with_code,
            is_unlimited=user.is_unlimited,
            created_at=self._restore_datetime(user.created_at),
            updated_at=self._restore_datetime(user.updated_at),
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

    def _restore_date(self, value: date | None) -> date | None:
        return value
