from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StartCallRequest(BaseModel):
    customer_id: str = "C001"


class TranscriptRequest(BaseModel):
    segment_id: str
    revision: int = Field(ge=1)
    is_final: bool = True
    speaker: str = "CUSTOMER"
    text: str = Field(min_length=1)
    language: str = "en"
    source_timestamp: datetime | None = None


class EmptyRequest(BaseModel):
    pass
