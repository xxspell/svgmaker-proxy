from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TelegramInviteCodeType(StrEnum):
    unlimited = "unlimited"


class TelegramUserRecord(BaseModel):
    id: int
    telegram_user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    display_name: str
    quota_remaining: int = 0
    initial_grant_applied: bool = False
    last_daily_grant_on: date | None = None
    last_generation_at: datetime | None = None
    started_with_code: str | None = None
    is_unlimited: bool = False
    created_at: datetime
    updated_at: datetime


class TelegramUserCreate(BaseModel):
    telegram_user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    display_name: str = Field(min_length=1, max_length=255)
    quota_remaining: int = 0
    initial_grant_applied: bool = False
    last_daily_grant_on: date | None = None
    last_generation_at: datetime | None = None
    started_with_code: str | None = None
    is_unlimited: bool = False


class TelegramUserUpdate(BaseModel):
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    display_name: str | None = None
    quota_remaining: int | None = None
    initial_grant_applied: bool | None = None
    last_daily_grant_on: date | None = None
    last_generation_at: datetime | None = None
    started_with_code: str | None = None
    is_unlimited: bool | None = None


class TelegramInviteCodeRecord(BaseModel):
    id: int
    code: str
    code_type: TelegramInviteCodeType
    description: str | None = None
    max_uses: int | None = None
    use_count: int = 0
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class TelegramInviteCodeCreate(BaseModel):
    code: str = Field(min_length=8, max_length=128)
    code_type: TelegramInviteCodeType = TelegramInviteCodeType.unlimited
    description: str | None = None
    max_uses: int | None = Field(default=None, ge=1)
    is_active: bool = True


class TelegramInviteCodeUpdate(BaseModel):
    description: str | None = None
    max_uses: int | None = Field(default=None, ge=1)
    use_count: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
