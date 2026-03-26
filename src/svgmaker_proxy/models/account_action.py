from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AccountActionType(StrEnum):
    account_created = "account_created"
    firebase_signup_succeeded = "firebase_signup_succeeded"
    display_name_updated = "display_name_updated"
    verification_email_requested = "verification_email_requested"
    initial_login_succeeded = "initial_login_succeeded"
    verification_email_received = "verification_email_received"
    email_verified = "email_verified"
    firebase_refresh_succeeded = "firebase_refresh_succeeded"
    verified_login_succeeded = "verified_login_succeeded"
    user_init_succeeded = "user_init_succeeded"
    credits_checked = "credits_checked"
    firestore_user_document_fetched = "firestore_user_document_fetched"
    post_signup_survey_completed = "post_signup_survey_completed"
    tour_completed = "tour_completed"
    preferences_updated = "preferences_updated"
    account_activated = "account_activated"
    account_refresh_succeeded = "account_refresh_succeeded"
    generation_started = "generation_started"
    generation_balance_snapshot = "generation_balance_snapshot"
    generation_completed = "generation_completed"
    generation_failed = "generation_failed"
    account_marked_failed = "account_marked_failed"


class AccountActionRecord(BaseModel):
    id: int
    account_id: int
    action_type: AccountActionType
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AccountActionCreate(BaseModel):
    account_id: int
    action_type: AccountActionType
    details: dict[str, Any] = Field(default_factory=dict)
