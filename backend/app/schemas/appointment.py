"""Pydantic models for appointment booking."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AppointmentStatus(str, Enum):
    """Lifecycle state of an appointment."""

    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Appointment(BaseModel):
    """A booked appointment, linked to a lead and/or call when known."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Appointment id (MongoDB document id).")
    lead_id: Optional[str] = None
    call_id: Optional[str] = None
    conversation_id: Optional[str] = None
    phone: Optional[str] = None
    customer_name: Optional[str] = None
    title: str = "Sales consultation"
    notes: Optional[str] = None
    scheduled_at: datetime = Field(description="When the appointment starts (UTC).")
    duration_minutes: int = 30
    status: AppointmentStatus = AppointmentStatus.SCHEDULED
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AppointmentCreateRequest(BaseModel):
    """Request body for POST /api/appointments."""

    model_config = ConfigDict(extra="forbid")

    scheduled_at: datetime = Field(description="Appointment start time (ISO 8601).")
    title: str = Field(default="Sales consultation", description="Short appointment title.")
    duration_minutes: int = Field(default=30, ge=5, le=480, description="Length in minutes.")
    lead_id: Optional[str] = Field(default=None, description="CRM lead to link.")
    phone: Optional[str] = Field(default=None, description="Customer phone (links to a lead).")
    customer_name: Optional[str] = None
    call_id: Optional[str] = Field(default=None, description="Related call id.")
    conversation_id: Optional[str] = Field(default=None, description="Related conversation id.")
    notes: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("title must not be empty")
        return value

    @field_validator("customer_name", "notes", "phone", "lead_id", "call_id", "conversation_id")
    @classmethod
    def blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def needs_an_owner(self) -> "AppointmentCreateRequest":
        """An appointment must link to a lead or carry a phone number."""
        if not self.lead_id and not self.phone:
            raise ValueError("Provide lead_id or phone so the appointment links to a customer.")
        return self


class AppointmentUpdateRequest(BaseModel):
    """Fields that can be changed through PATCH /api/appointments/{id}."""

    model_config = ConfigDict(extra="forbid")

    scheduled_at: Optional[datetime] = None
    title: Optional[str] = None
    duration_minutes: Optional[int] = Field(default=None, ge=5, le=480)
    status: Optional[AppointmentStatus] = None
    notes: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("title must not be empty")
        return value


class AppointmentListResponse(BaseModel):
    """Response body for GET /api/appointments."""

    total: int
    count: int
    appointments: list[Appointment]
