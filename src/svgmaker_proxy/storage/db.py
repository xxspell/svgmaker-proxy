from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from svgmaker_proxy.core.config import Settings, get_settings


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            self._engine = create_async_engine(
                self.settings.database_url,
                future=True,
                pool_pre_ping=True,
                echo=False,
            )
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            self._session_factory = async_sessionmaker(
                self.engine,
                expire_on_commit=False,
                class_=AsyncSession,
                autoflush=False,
                autocommit=False,
            )
        return self._session_factory

    async def initialize(self) -> None:
        """Warm up engine connectivity.

        Schema management is handled by Alembic, so startup only ensures the
        engine can connect successfully.
        """
        async with self.engine.begin() as connection:
            await connection.run_sync(lambda _: None)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        session = self.session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


_database: Database | None = None


def get_database() -> Database:
    global _database
    if _database is None:
        _database = Database()
    return _database


@asynccontextmanager
async def get_db_session() -> AsyncIterator[AsyncSession]:
    database = get_database()
    async with database.session() as session:
        yield session


async def get_db_session_dependency() -> AsyncIterator[AsyncSession]:
    async with get_db_session() as session:
        yield session


def sqlalchemy_model_to_dict(model: Any) -> dict[str, Any]:
    return {
        column.key: getattr(model, column.key)
        for column in model.__table__.columns  # type: ignore[attr-defined]
    }
