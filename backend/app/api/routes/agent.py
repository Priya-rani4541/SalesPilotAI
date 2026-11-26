"""Sales agent chat endpoint."""

import logging

from fastapi import APIRouter, HTTPException

from app.schemas.agent import AgentChatRequest, AgentChatResponse
from app.services.conversation_store import (
    ConversationNotFoundError,
    ConversationStore,
    ConversationStoreError,
)
from app.services.lead_service import LeadService
from app.services.lead_store import LeadStore
from app.services.sales_agent import (
    AgentConfigurationError,
    AgentRateLimitError,
    AgentUpstreamError,
    SalesAgent,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_agent = SalesAgent(ConversationStore())
# Keeps the CRM in sync with what the agent collects (best effort).
_leads = LeadService(LeadStore())


@router.post(
    "/chat",
    response_model=AgentChatResponse,
    summary="Send a message to the Gemini sales agent",
)
def chat(payload: AgentChatRequest) -> AgentChatResponse:
    """Run one conversation turn and return the reply plus the collected lead."""
    try:
        conversation, turn = _agent.chat(payload.message, payload.conversation_id)
    except ConversationNotFoundError as exc:
        # The supplied conversation id does not exist in the database.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConversationStoreError as exc:
        # The database is not configured or is temporarily unavailable.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AgentConfigurationError as exc:
        # The server is missing its Gemini credentials.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AgentRateLimitError as exc:
        # Gemini quota exceeded; tell the client to retry later.
        raise HTTPException(
            status_code=429, detail=str(exc), headers={"Retry-After": "60"}
        ) from exc
    except AgentUpstreamError as exc:
        # Gemini failed or returned something unusable.
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Best-effort CRM sync: a CRM problem must never change the chat response.
    # allow_partial keeps a chat that only captured a name (no phone) in Leads.
    try:
        _leads.sync_from_conversation(conversation, allow_partial=True)
    except Exception:  # noqa: BLE001 - CRM sync is not allowed to break the chat API
        logger.warning("Lead sync failed for conversation %s", conversation.id)

    missing_fields = conversation.lead.missing_fields()
    return AgentChatResponse(
        conversation_id=conversation.id,
        response=turn.response,
        lead=conversation.lead,
        missing_fields=missing_fields,
        is_lead_complete=not missing_fields,
        turn=conversation.turn_count,
    )
