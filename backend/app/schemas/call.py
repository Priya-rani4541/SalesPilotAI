"""Pydantic models for the read-only call history API."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CallRecord(BaseModel):
    """A stored Vapi call (subset of the "calls" collection document)."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Vapi call id (MongoDB document id).")
    conversation_id: Optional[str] = None
    phone_number: Optional[str] = None
    direction: Optional[str] = None
    call_type: Optional[str] = None
    status: Optional[str] = None
    ended_reason: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    cost: Optional[float] = None
    transcript: Optional[str] = None
    summary: Optional[str] = None
    recording_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CallListResponse(BaseModel):
    """Response body for GET /api/calls."""

    total: int
    count: int
    calls: list[CallRecord]
