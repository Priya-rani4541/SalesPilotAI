"""Pydantic models for lead qualification and the MongoDB CRM.

`Lead` is the CRM record stored in the "leads" collection. `LeadUpdateRequest`
is the body accepted by PATCH /api/leads/{id}; unknown fields are rejected so
bad input is caught at the API boundary.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InterestLevel(str, Enum):
    """How interested (and ready to buy) a lead appears to be."""

    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"


class LeadStatus(str, Enum):
    """Sales-pipeline stage of a lead. Changed only through the update API."""

    NEW = "NEW"
    CONTACTED = "CONTACTED"
    QUALIFIED = "QUALIFIED"
    CONVERTED = "CONVERTED"
    LOST = "LOST"


class CallHistoryEntry(BaseModel):
    """One voice call recorded against a lead."""

    model_config = ConfigDict(extra="ignore")

    call_id: str
    conversation_id: Optional[str] = None
    direction: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    summary: Optional[str] = None
    transcript: Optional[str] = None


class Lead(BaseModel):
    """A qualified lead stored in the CRM."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Lead id (MongoDB document id).")
    name: Optional[str] = None
    phone: Optional[str] = Field(
        default=None, description="Phone number as it was given; None when not collected."
    )
    phone_normalized: str = Field(
        default="",
        description="Canonical digits-only phone used to detect duplicates; empty when no phone.",
    )
    budget: Optional[str] = None
    product_interest: Optional[str] = Field(
        default=None, description="Product or service the customer is interested in."
    )
    purchase_timeline: Optional[str] = Field(
        default=None, description="When the customer plans to buy or get started."
    )
    requirements: Optional[str] = Field(
        default=None, description="What the customer is looking for."
    )
    interest_level: InterestLevel = InterestLevel.COLD
    status: LeadStatus = LeadStatus.NEW
    notes: Optional[str] = None
    conversation_ids: list[str] = Field(default_factory=list)
    call_ids: list[str] = Field(default_factory=list)
    call_history: list[CallHistoryEntry] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class LeadUpdateRequest(BaseModel):
    """Fields that can be changed through PATCH /api/leads/{id}."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    budget: Optional[str] = None
    requirements: Optional[str] = None
    interest_level: Optional[InterestLevel] = None
    status: Optional[LeadStatus] = None
    notes: Optional[str] = None

    @field_validator("name", "budget", "requirements", "notes")
    @classmethod
    def blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        """Treat blank strings as "not provided" instead of overwriting with ""."""
        if value is None:
            return None
        value = value.strip()
        return value or None


class LeadListResponse(BaseModel):
    """Response body for GET /api/leads."""

    total: int = Field(description="Number of leads matching the filters.")
    count: int = Field(description="Number of leads returned in this page.")
    leads: list[Lead]
