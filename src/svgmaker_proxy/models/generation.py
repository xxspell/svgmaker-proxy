from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class GenerationStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class EditSourceMode(StrEnum):
    svg_text = "svg_text"
    upload = "upload"


class EditRequestRecord(BaseModel):
    id: int
    external_generation_id: str | None = None
    account_id: int
    prompt: str
    quality: str
    aspect_ratio: str
    background: str
    source_mode: EditSourceMode
    source_filename: str | None = None
    status: GenerationStatus
    credit_cost: int | None = None
    svg_url: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


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


class EditRequestCreate(BaseModel):
    account_id: int
    prompt: str = Field(min_length=1)
    quality: str = "high"
    aspect_ratio: str = "auto"
    background: str = "auto"
    source_mode: EditSourceMode
    source_filename: str | None = None
    status: GenerationStatus = GenerationStatus.queued
    external_generation_id: str | None = None
    credit_cost: int | None = None
    svg_url: str | None = None
    error_message: str | None = None


class EditRequestUpdate(BaseModel):
    account_id: int | None = None
    external_generation_id: str | None = None
    status: GenerationStatus | None = None
    credit_cost: int | None = None
    svg_url: str | None = None
    error_message: str | None = None


class SvgmakerEditRequest(BaseModel):
    prompt: str = Field(min_length=1)
    quality: str = "high"
    aspect_ratio: str = "auto"
    background: str = "auto"
    stream: bool = True
    svg_text: bool = True
    source_svg_text: str | None = None
    source_file_content: bytes | None = None
    source_filename: str | None = None
    source_content_type: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> SvgmakerEditRequest:
        has_text = bool(self.source_svg_text and self.source_svg_text.strip())
        has_file = bool(self.source_file_content)
        if has_text == has_file:
            raise ValueError("Provide exactly one SVG source: text or uploaded file")
        return self

    @property
    def source_mode(self) -> EditSourceMode:
        return (
            EditSourceMode.svg_text if self.source_svg_text is not None else EditSourceMode.upload
        )


class SvgmakerEditResult(BaseModel):
    generation_id: str
    svg_url: str
    quality: str
    credit_cost: int | None = None
    svg_text: str | None = None


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
