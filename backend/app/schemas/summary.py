"""Pydantic models for call summaries.

A call summary is produced from a call transcript (a Vapi call or a web
conversation) and stored in the "call_summaries" collection. `CallSummaryDraft`
is the structured output Gemini must return; `CallSummary` is the stored/returned
record.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Sentiment(str, Enum):
    """Overall customer sentiment detected in the conversation."""

    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


class CallSummaryDraft(BaseModel):
    """Structured summary Gemini must return for a transcript."""

    summary: str = Field(description="A concise 2-4 sentence summary of the call.")
    requirements: list[str] = Field(
        default_factory=list, description="What the customer is looking for."
    )
    objections: list[str] = Field(
        default_factory=list, description="Concerns or objections the customer raised."
    )
    sentiment: Sentiment = Field(description="Overall customer sentiment.")
    follow_up_actions: list[str] = Field(
        default_factory=list, description="Recommended next steps for the sales team."
    )


class CallSummary(BaseModel):
    """A stored call summary, linked to its call, conversation and lead."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Summary id (MongoDB document id).")
    call_id: Optional[str] = None
    conversation_id: Optional[str] = None
    lead_id: Optional[str] = None
    phone: Optional[str] = None
    summary: str
    requirements: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    sentiment: Sentiment = Sentiment.NEUTRAL
    follow_up_actions: list[str] = Field(default_factory=list)
    model: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SummaryGenerateRequest(BaseModel):
    """Request body for POST /api/summaries/generate.

    Exactly one source must be supplied: an existing call id, an existing
    conversation id, or a raw transcript.
    """

    model_config = ConfigDict(extra="forbid")

    call_id: Optional[str] = Field(default=None, description="Summarise this stored call.")
    conversation_id: Optional[str] = Field(
        default=None, description="Summarise this stored conversation."
    )
    transcript: Optional[str] = Field(
        default=None, description="Summarise this raw transcript text."
    )

    @model_validator(mode="after")
    def exactly_one_source(self) -> "SummaryGenerateRequest":
        sources = [self.call_id, self.conversation_id, self.transcript]
        provided = [source for source in sources if source and source.strip()]
        if not provided:
            raise ValueError("Provide one of call_id, conversation_id or transcript.")
        if len(provided) > 1:
            raise ValueError("Provide only one of call_id, conversation_id or transcript.")
        return self


class SummaryListResponse(BaseModel):
    """Response body for GET /api/summaries."""

    total: int = Field(description="Number of summaries matching the filters.")
    count: int = Field(description="Number of summaries returned in this page.")
    summaries: list[CallSummary]
