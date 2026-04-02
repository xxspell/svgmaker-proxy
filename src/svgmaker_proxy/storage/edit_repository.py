from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Select, select

from svgmaker_proxy.models.generation import (
    EditRequestCreate,
    EditRequestRecord,
    EditRequestUpdate,
    EditSourceMode,
    GenerationStatus,
)
from svgmaker_proxy.storage.db import get_db_session
from svgmaker_proxy.storage.orm import EditRequestORM


class EditRepository:
    async def create(self, payload: EditRequestCreate) -> EditRequestRecord:
        now = datetime.now(UTC).replace(tzinfo=None)
        request = EditRequestORM(
            external_generation_id=payload.external_generation_id,
            account_id=payload.account_id,
            prompt=payload.prompt,
            quality=payload.quality,
            aspect_ratio=payload.aspect_ratio,
            background=payload.background,
            source_mode=payload.source_mode.value,
            source_filename=payload.source_filename,
            status=payload.status.value,
            credit_cost=payload.credit_cost,
            svg_url=payload.svg_url,
            error_message=payload.error_message,
            created_at=now,
            updated_at=now,
        )

        async with get_db_session() as session:
            session.add(request)
            await session.flush()
            await session.refresh(request)
            return self._orm_to_model(request)

    async def get_by_id(self, request_id: int) -> EditRequestRecord | None:
        statement = select(EditRequestORM).where(EditRequestORM.id == request_id)
        return await self._fetch_one(statement)

    async def list_recent(self, limit: int = 100) -> list[EditRequestRecord]:
        statement = select(EditRequestORM).order_by(EditRequestORM.id.desc()).limit(limit)
        return await self._fetch_many(statement)

    async def update(self, request_id: int, payload: EditRequestUpdate) -> EditRequestRecord | None:
        values = payload.model_dump(exclude_none=True)
        if not values:
            return await self.get_by_id(request_id)

        async with get_db_session() as session:
            request = await session.get(EditRequestORM, request_id)
            if request is None:
                return None

            for key, value in values.items():
                if isinstance(value, GenerationStatus):
                    value = value.value
                setattr(request, key, value)

            request.updated_at = datetime.now(UTC).replace(tzinfo=None)
            await session.flush()
            await session.refresh(request)
            return self._orm_to_model(request)

    async def _fetch_one(
        self, statement: Select[tuple[EditRequestORM]]
    ) -> EditRequestRecord | None:
        async with get_db_session() as session:
            result = await session.execute(statement)
            request = result.scalar_one_or_none()
        return self._orm_to_model(request) if request is not None else None

    async def _fetch_many(
        self, statement: Select[tuple[EditRequestORM]]
    ) -> list[EditRequestRecord]:
        async with get_db_session() as session:
            result = await session.execute(statement)
            requests = result.scalars().all()
        return [self._orm_to_model(request) for request in requests]

    def _orm_to_model(self, request: EditRequestORM) -> EditRequestRecord:
        return EditRequestRecord(
            id=request.id,
            external_generation_id=request.external_generation_id,
            account_id=request.account_id,
            prompt=request.prompt,
            quality=request.quality,
            aspect_ratio=request.aspect_ratio,
            background=request.background,
            source_mode=EditSourceMode(request.source_mode),
            source_filename=request.source_filename,
            status=GenerationStatus(request.status),
            credit_cost=request.credit_cost,
            svg_url=request.svg_url,
            error_message=request.error_message,
            created_at=self._restore_datetime(request.created_at),
            updated_at=self._restore_datetime(request.updated_at),
        )

    def _restore_datetime(self, value: datetime | None) -> datetime:
        if value is None:
            raise ValueError("Expected datetime, got None")
        if value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)
