from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field


class AccountStatus(StrEnum):
    pending = "pending"
    verifying_email = "verifying_email"
    active = "active"
    cooling_down = "cooling_down"
    blocked = "blocked"
    failed = "failed"


class AccountRecord(BaseModel):
    id: int
    email: EmailStr
    password: str
    display_name: str
    status: AccountStatus
    email_verified: bool = False
    firebase_local_id: str | None = None
    firebase_id_token: str | None = None
    firebase_refresh_token: str | None = None
    svgmaker_auth_token_id: str | None = None
    svgmaker_auth_token_refresh: str | None = None
    svgmaker_auth_token_sig: str | None = None
    credits_last_known: int | None = None
    last_generation_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    last_checked_at: datetime | None = None
    failure_count: int = 0
    created_at: datetime
    updated_at: datetime

    @property
    def has_complete_svgmaker_session(self) -> bool:
        return bool(
            self.svgmaker_auth_token_id
            and self.svgmaker_auth_token_refresh
            and self.svgmaker_auth_token_sig
        )

    @property
    def is_ready(self) -> bool:
        return (
            self.status is AccountStatus.active
            and self.email_verified
            and self.has_complete_svgmaker_session
        )


class AccountCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=2, max_length=64)
    status: AccountStatus = AccountStatus.pending
    email_verified: bool = False
    firebase_local_id: str | None = None
    firebase_id_token: str | None = None
    firebase_refresh_token: str | None = None
    svgmaker_auth_token_id: str | None = None
    svgmaker_auth_token_refresh: str | None = None
    svgmaker_auth_token_sig: str | None = None
    credits_last_known: int | None = None
    last_generation_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    last_checked_at: datetime | None = None
    failure_count: int = 0


class AccountUpdate(BaseModel):
    display_name: str | None = None
    status: AccountStatus | None = None
    email_verified: bool | None = None
    firebase_local_id: str | None = None
    firebase_id_token: str | None = None
    firebase_refresh_token: str | None = None
    svgmaker_auth_token_id: str | None = None
    svgmaker_auth_token_refresh: str | None = None
    svgmaker_auth_token_sig: str | None = None
    credits_last_known: int | None = None
    last_generation_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    last_checked_at: datetime | None = None
    failure_count: int | None = None
