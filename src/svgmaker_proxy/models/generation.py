from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class GenerationStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class GenerationRequestRecord(BaseModel):
    id: int
    external_generation_id: str | None = None
    account_id: int
    prompt: str
    quality: str
    aspect_ratio: str
    background: str
    status: GenerationStatus
    credit_cost: int | None = None
    svg_url: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class GenerationRequestCreate(BaseModel):
    account_id: int
    prompt: str = Field(min_length=1)
    quality: str = "high"
    aspect_ratio: str = "auto"
    background: str = "auto"
    status: GenerationStatus = GenerationStatus.queued
    external_generation_id: str | None = None
    credit_cost: int | None = None
    svg_url: str | None = None
    error_message: str | None = None


class GenerationRequestUpdate(BaseModel):
    account_id: int | None = None
    external_generation_id: str | None = None
    status: GenerationStatus | None = None
    credit_cost: int | None = None
    svg_url: str | None = None
    error_message: str | None = None


class SvgmakerGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    quality: str = "high"
    aspect_ratio: str = "auto"
    background: str = "auto"
    stream: bool = True
    base64_png: bool = False
    svg_text: bool = True
    style_params: dict[str, Any] = Field(default_factory=dict)


class SvgmakerGenerationResult(BaseModel):
    generation_id: str
    svg_url: str
    quality: str
    credit_cost: int | None = None
    svg_text: str | None = None
