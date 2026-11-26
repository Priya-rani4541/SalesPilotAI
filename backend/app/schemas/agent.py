"""Pydantic models shared by the sales agent API and Gemini structured output."""

from typing import Optional

from pydantic import BaseModel, Field, field_validator

# The five lead details the agent must collect during a conversation.
LEAD_FIELDS: tuple[str, ...] = (
    "name",
    "phone",
    "budget",
    "product_interest",
    "purchase_timeline",
)


class LeadInfo(BaseModel):
    """Lead details collected from the customer during the conversation."""

    name: Optional[str] = Field(default=None, description="Customer's full name.")
    phone: Optional[str] = Field(default=None, description="Customer's contact phone number.")
    budget: Optional[str] = Field(default=None, description="Budget the customer mentioned.")
    product_interest: Optional[str] = Field(
        default=None, description="Product or use case the customer is interested in."
    )
    purchase_timeline: Optional[str] = Field(
        default=None, description="When the customer plans to buy or get started."
    )

    def missing_fields(self) -> list[str]:
        """Return the lead fields that have not been collected yet.

        This is a deterministic check, so lead completion never depends on the
        model's own opinion of whether the conversation is finished.
        """
        return [field for field in LEAD_FIELDS if not getattr(self, field)]


class AgentTurn(BaseModel):
    """Structured output Gemini must return for every conversation turn."""

    response: str = Field(description="Natural language reply to show the customer.")
    lead: LeadInfo = Field(
        description="Lead details collected so far. Use null for anything not yet provided."
    )


class AgentChatRequest(BaseModel):
    """Request body for POST /api/agent/chat."""

    message: str = Field(description="The customer's message.")
    conversation_id: Optional[str] = Field(
        default=None,
        description="Existing conversation id. Omit it to start a new conversation.",
    )

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be empty")
        return value


class AgentChatResponse(BaseModel):
    """Response body for POST /api/agent/chat."""

    conversation_id: str = Field(description="Use this id to continue the conversation.")
    response: str = Field(description="The sales agent's natural language reply.")
    lead: LeadInfo = Field(description="Lead details collected so far.")
    missing_fields: list[str] = Field(description="Lead fields still missing.")
    is_lead_complete: bool = Field(description="True when all five lead fields are collected.")
    turn: int = Field(description="Number of customer messages in this conversation.")
