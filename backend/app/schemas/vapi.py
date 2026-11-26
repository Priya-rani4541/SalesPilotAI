"""Pydantic models for the Vapi voice integration.

The Custom LLM endpoint receives an OpenAI-compatible chat-completions request;
the webhook receives Vapi "server messages". Both payloads contain many more
fields than the backend needs, so the models are deliberately permissive
(extra="ignore") and only name the fields the backend acts on.
"""

import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def content_to_text(content: Any) -> str:
    """Flatten an OpenAI-style message content value into plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return " ".join(part for part in parts if part)
    return str(content)


class VapiMessage(BaseModel):
    """One message in the OpenAI-style conversation Vapi sends us."""

    model_config = ConfigDict(extra="ignore")

    role: str
    content: Any = None

    def text(self) -> str:
        return content_to_text(self.content)


class VapiCallRef(BaseModel):
    """The subset of the Vapi call object the backend uses."""

    model_config = ConfigDict(extra="ignore")

    id: Optional[str] = None
    type: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    customer: Optional[dict[str, Any]] = None
    phoneNumber: Optional[dict[str, Any]] = None
    startedAt: Optional[str] = None
    endedAt: Optional[str] = None


class VapiChatRequest(BaseModel):
    """OpenAI-compatible body Vapi posts to the Custom LLM endpoint."""

    model_config = ConfigDict(extra="ignore")

    model: Optional[str] = None
    messages: list[VapiMessage] = Field(default_factory=list)
    stream: bool = True
    call: Optional[VapiCallRef] = None

    def last_user_text(self) -> str:
        """Return the most recent user message, or an empty string if there is none."""
        for message in reversed(self.messages):
            if message.role == "user":
                return message.text().strip()
        return ""


class OutboundCallRequest(BaseModel):
    """Request body for POST /api/vapi/call (start an outbound call).

    Carries the number to dial plus optional lead context: the CRM lead to link
    the call to, an existing conversation, an assistant override and the name to
    greet the customer with.
    """

    model_config = ConfigDict(extra="forbid")

    phone_number: str = Field(description="Customer phone number to dial, in E.164 format.")
    lead_id: Optional[str] = Field(
        default=None,
        description="Existing CRM lead id to link the call to (from GET /api/leads).",
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="Existing conversation id to attach to the call. Generated when omitted.",
    )
    assistant_id: Optional[str] = Field(
        default=None,
        description="Vapi assistant id. Falls back to VAPI_ASSISTANT_ID.",
    )
    customer_name: Optional[str] = Field(
        default=None,
        description="Name used to greet the customer (passed to the assistant).",
    )

    @field_validator("phone_number")
    @classmethod
    def _require_dialable_number(cls, value: str) -> str:
        """Reject numbers that clearly cannot be dialled (fewer than 8 digits)."""
        digits = re.sub(r"\D+", "", value or "")
        if len(digits) < 8:
            raise ValueError("phone_number must contain at least 8 digits.")
        return value.strip()

    @field_validator("lead_id", "conversation_id", "assistant_id", "customer_name")
    @classmethod
    def _blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        """Treat blank strings as "not provided" instead of forwarding empty text."""
        if value is None:
            return None
        value = value.strip()
        return value or None
