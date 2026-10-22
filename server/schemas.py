from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ContentType = Literal["auto", "meeting", "course"]


class PairRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32)
    device_name: str = Field(min_length=1, max_length=80)
    role: Literal["phone", "pc"]

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("device_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("设备名不能为空")
        return value


class RecordingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content_type: ContentType = "auto"
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    duration_s: float | None = Field(default=None, ge=0, le=7 * 24 * 3600)
    client_upload_id: str | None = Field(default=None, max_length=80)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("标题不能为空")
        return value

    @field_validator("sha256")
    @classmethod
    def lower_sha(cls, value: str) -> str:
        return value.lower()


class PinRequest(BaseModel):
    pinned: bool


class FailRequest(BaseModel):
    error: str = Field(default="", max_length=2000)
