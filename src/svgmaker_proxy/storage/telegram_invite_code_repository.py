from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from svgmaker_proxy.models.telegram import (
    TelegramInviteCodeCreate,
    TelegramInviteCodeRecord,
    TelegramInviteCodeType,
    TelegramInviteCodeUpdate,
)
from svgmaker_proxy.storage.db import get_db_session
from svgmaker_proxy.storage.orm import TelegramInviteCodeORM


class TelegramInviteCodeRepository:
    async def create(self, payload: TelegramInviteCodeCreate) -> TelegramInviteCodeRecord:
        now = datetime.now(UTC).replace(tzinfo=None)
        code = TelegramInviteCodeORM(
            code=payload.code,
            code_type=payload.code_type.value,
            description=payload.description,
            max_uses=payload.max_uses,
            use_count=0,
            is_active=payload.is_active,
            created_at=now,
            updated_at=now,
        )
        async with get_db_session() as session:
            session.add(code)
            await session.flush()
            await session.refresh(code)
            return self._orm_to_model(code)

    async def get_by_code(self, code: str) -> TelegramInviteCodeRecord | None:
        statement = select(TelegramInviteCodeORM).where(TelegramInviteCodeORM.code == code)
        async with get_db_session() as session:
            result = await session.execute(statement)
            invite = result.scalar_one_or_none()
        return self._orm_to_model(invite) if invite is not None else None

    async def update(
        self,
        code: str,
        payload: TelegramInviteCodeUpdate,
    ) -> TelegramInviteCodeRecord | None:
        values = payload.model_dump(exclude_none=True)
        async with get_db_session() as session:
            statement = select(TelegramInviteCodeORM).where(TelegramInviteCodeORM.code == code)
            result = await session.execute(statement)
            invite = result.scalar_one_or_none()
            if invite is None:
                return None

            for key, value in values.items():
                setattr(invite, key, value)
            invite.updated_at = datetime.now(UTC).replace(tzinfo=None)
            await session.flush()
            await session.refresh(invite)
            return self._orm_to_model(invite)

    def _orm_to_model(self, invite: TelegramInviteCodeORM) -> TelegramInviteCodeRecord:
        return TelegramInviteCodeRecord(
            id=invite.id,
            code=invite.code,
            code_type=TelegramInviteCodeType(invite.code_type),
            description=invite.description,
            max_uses=invite.max_uses,
            use_count=invite.use_count,
            is_active=invite.is_active,
            created_at=self._restore_datetime(invite.created_at),
            updated_at=self._restore_datetime(invite.updated_at),
        )

    def _restore_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)
