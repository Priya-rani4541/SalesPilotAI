"""Vapi voice integration endpoints.

- POST /api/vapi/llm/chat/completions : OpenAI-compatible endpoint used by
  Vapi's Custom LLM feature to drive the existing Gemini sales engine in real
  time. The reply text is streamed back as Server-Sent Events.
- POST /api/vapi/webhook : receives Vapi server messages (call start, status,
  end-of-call report, transcript, summary) and stores them in MongoDB.
- POST /api/vapi/call : starts an outbound call through the Vapi REST API.

Every endpoint is protected by the shared secret in VAPI_WEBHOOK_SECRET, sent by
Vapi as the `x-vapi-secret` header (an `Authorization: Bearer` token is also
accepted). When no secret is configured the check is skipped and a warning is
logged at startup so development keeps working.
"""

import hmac
import json
import logging
import re
import time
import uuid
from typing import Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.schemas.vapi import OutboundCallRequest, VapiChatRequest
from app.services.conversation_store import CallStore, ConversationStore, ConversationStoreError
from app.services.lead_service import LeadService
from app.services.lead_store import LeadStore
from app.services.sales_agent import (
    AgentConfigurationError,
    AgentRateLimitError,
    AgentUpstreamError,
    SalesAgent,
)
from app.services.summary_service import SummaryService
from app.services.summary_store import SummaryStore
from app.services.vapi_service import (
    VapiConfigurationError,
    VapiRequestError,
    VapiService,
    VapiTurnResult,
    VapiUpstreamError,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# One shared engine and store, mirroring app/api/routes/agent.py.
_conversations = ConversationStore()
_calls = CallStore()
_leads = LeadService(LeadStore())
_service = VapiService(
    SalesAgent(_conversations),
    _conversations,
    _calls,
    _leads,
    SummaryService(SummaryStore()),
)


def _check_secret(request: Request) -> None:
    """Reject requests that do not present the configured shared secret."""
    secret = settings.VAPI_WEBHOOK_SECRET.strip()
    if not secret:
        return
    provided = request.headers.get("x-vapi-secret", "")
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if not provided or not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=401, detail="Invalid or missing Vapi secret.")


def _sse_chunk(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _iter_pieces(text: str) -> Iterator[str]:
    """Split the reply into small word-sized pieces so it streams naturally."""
    for token in re.findall(r"\S+\s*", text or ""):
        yield token


def _sse_stream(result: VapiTurnResult) -> Iterator[str]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    base = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": result.model,
    }
    yield _sse_chunk({**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
    for piece in _iter_pieces(result.text):
        yield _sse_chunk({**base, "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]})
    yield _sse_chunk({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    yield "data: [DONE]\n\n"


def _completion_json(result: VapiTurnResult) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": result.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.text},
                "finish_reason": "stop",
            }
        ],
    }


def _map_engine_errors(exc: Exception) -> HTTPException:
    """Translate an engine/store error into a clean HTTP response."""
    if isinstance(exc, VapiRequestError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, (ConversationStoreError, AgentConfigurationError, VapiConfigurationError)):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, AgentRateLimitError):
        return HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "30"})
    if isinstance(exc, (AgentUpstreamError, VapiUpstreamError)):
        return HTTPException(status_code=502, detail=str(exc))
    raise exc


@router.post(
    "/llm/chat/completions",
    summary="OpenAI-compatible endpoint used by Vapi Custom LLM",
)
def chat_completions(payload: VapiChatRequest, request: Request):
    """Run one voice turn on the existing Gemini engine and stream the reply."""
    _check_secret(request)
    try:
        result = _service.run_turn(payload)
    except Exception as exc:  # noqa: BLE001 - mapped to a clean HTTP error below
        raise _map_engine_errors(exc) from exc

    if payload.stream:
        return StreamingResponse(
            _sse_stream(result),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return _completion_json(result)


@router.post("/webhook", summary="Receive Vapi server messages")
async def webhook(request: Request) -> dict:
    """Persist call lifecycle, transcript and summary events from Vapi."""
    _check_secret(request)
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001 - malformed body from the caller
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc

    message = body.get("message") if isinstance(body, dict) else None
    if not isinstance(message, dict):
        raise HTTPException(status_code=422, detail="Missing 'message' object.")

    try:
        return _service.handle_webhook(message)
    except ConversationStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/call", summary="Start an outbound Vapi call")
def start_outbound_call(payload: OutboundCallRequest, request: Request) -> dict:
    """Ask Vapi to place an outbound call and record it in MongoDB."""
    _check_secret(request)
    try:
        return _service.start_outbound_call(
            phone_number=payload.phone_number,
            conversation_id=payload.conversation_id,
            assistant_id=payload.assistant_id,
            lead_id=payload.lead_id,
            customer_name=payload.customer_name,
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a clean HTTP error below
        raise _map_engine_errors(exc) from exc
