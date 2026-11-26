"""Generate structured call summaries from a transcript.

The transcript can come from a stored Vapi call, a stored web conversation, or
be supplied directly. Gemini returns structured JSON (summary, requirements,
objections, sentiment, follow-up actions) which is validated and persisted in
MongoDB, linked to the call, conversation and (when known) the CRM lead.

Sentiment is intentionally produced by the model here - it is a narrative
judgement over the transcript, not a hard business rule.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from google import genai
from google.genai import types

from app.core.config import settings
from app.schemas.summary import (
    CallSummaryDraft,
    Sentiment,
    SummaryGenerateRequest,
)
from app.services.conversation_store import (
    CallStore,
    ConversationNotFoundError,
    ConversationStore,
)
from app.services.lead_service import normalize_phone
from app.services.lead_store import LeadStore
from app.services.summary_store import SummaryStore, SummaryStoreError

logger = logging.getLogger(__name__)


class SummaryError(Exception):
    """Base class for call summary errors."""


class SummaryInputError(SummaryError):
    """The request did not carry a usable transcript."""


class SummaryConfigurationError(SummaryError):
    """The server is missing its Gemini credentials."""


class SummaryRateLimitError(SummaryError):
    """Gemini rejected the request because the API quota was exceeded."""


class SummaryUpstreamError(SummaryError):
    """Gemini failed or returned unusable data."""


SYSTEM_PROMPT = """You are an expert sales analyst for SalesPilot AI.

Read the call transcript between an AI sales agent and a customer and produce a
structured summary. Base everything strictly on the transcript and never invent
details that are not present.

- summary: a concise 2-4 sentence overview of the call.
- requirements: what the customer is looking for (short phrases).
- objections: concerns or objections the customer raised (empty list if none).
- sentiment: POSITIVE, NEUTRAL or NEGATIVE based on the customer's overall tone.
- follow_up_actions: concrete next steps the sales team should take.

Keep every list item short (a phrase, not a paragraph). Reply in English."""

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Create the Gemini client once and reuse it."""
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY.strip():
            raise SummaryConfigurationError(
                "GEMINI_API_KEY is not configured on the server. "
                "Add it to backend/.env and restart the API."
            )
        _client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(api_version="v1beta"),
        )
    return _client


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def transcript_from_history(history: list[dict[str, str]]) -> str:
    """Turn stored conversation messages into a plain "role: text" transcript."""
    lines = []
    for entry in history:
        role = "Customer" if entry.get("role") == "user" else "Agent"
        text = (entry.get("text") or "").strip()
        if text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines)


class SummaryService:
    """Generates and stores call summaries, linked to calls, conversations and leads."""

    def __init__(
        self,
        store: SummaryStore,
        calls: CallStore | None = None,
        conversations: ConversationStore | None = None,
        leads: LeadStore | None = None,
    ) -> None:
        self._store = store
        self._calls = calls or CallStore()
        self._conversations = conversations or ConversationStore()
        self._leads = leads or LeadStore()

    # --- transcript resolution ------------------------------------------------

    def _resolve_transcript(
        self, request: SummaryGenerateRequest
    ) -> tuple[str, dict[str, Any]]:
        """Return (transcript, context) where context has call/conversation/phone."""
        context: dict[str, Any] = {}
        if request.transcript and request.transcript.strip():
            return request.transcript.strip(), context

        if request.call_id:
            document = self._calls.get(request.call_id)
            if document is None:
                raise SummaryInputError(f"Call '{request.call_id}' was not found.")
            context["call_id"] = str(document.get("_id"))
            context["conversation_id"] = document.get("conversation_id")
            context["phone"] = document.get("phone_number")
            transcript = (document.get("transcript") or "").strip()
            if not transcript:
                raise SummaryInputError(
                    "That call has no transcript yet, so it cannot be summarised."
                )
            return transcript, context

        # conversation_id
        try:
            conversation = self._conversations.get_or_create(request.conversation_id)
        except ConversationNotFoundError as exc:
            raise SummaryInputError(f"Conversation '{request.conversation_id}' was not found.") from exc
        context["conversation_id"] = conversation.id
        context["phone"] = conversation.lead.phone
        transcript = transcript_from_history(conversation.history).strip()
        if not transcript:
            raise SummaryInputError("That conversation has no messages to summarise.")
        return transcript, context

    # --- Gemini ---------------------------------------------------------------

    def _summarize(self, transcript: str) -> tuple[CallSummaryDraft, str]:
        """Ask Gemini to summarise the transcript and validate the structured output."""
        client = _get_client()
        try:
            result = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=transcript,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=settings.GEMINI_TEMPERATURE,
                    response_mime_type="application/json",
                    response_schema=CallSummaryDraft,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - any SDK failure becomes a clean error
            logger.error("Gemini summary request failed (%s)", type(exc).__name__)
            if getattr(exc, "code", None) == 429:
                raise SummaryRateLimitError(
                    "The AI service is rate limited right now. Please retry in a moment."
                ) from exc
            raise SummaryUpstreamError(
                "The AI service is currently unavailable. Please try again."
            ) from exc

        draft = result.parsed
        if not isinstance(draft, CallSummaryDraft):
            logger.error("Gemini returned a summary that did not match the schema")
            raise SummaryUpstreamError("The AI service returned an unexpected response.")
        return draft, settings.GEMINI_MODEL

    # --- linking --------------------------------------------------------------

    def _resolve_lead_id(self, context: dict[str, Any]) -> str | None:
        """Find the CRM lead this summary belongs to, if any."""
        conversation_id = context.get("conversation_id")
        phone = context.get("phone")
        try:
            if conversation_id:
                lead = self._leads.find_by_conversation(str(conversation_id))
                if lead:
                    return lead.get("_id")
            phone_normalized = normalize_phone(phone)
            if phone_normalized:
                lead = self._leads.find_by_phone(phone_normalized)
                if lead:
                    return lead.get("_id")
        except Exception as exc:  # noqa: BLE001 - linking must not break the summary
            logger.warning("Lead lookup for summary failed (%s)", type(exc).__name__)
        return None

    # --- public API -----------------------------------------------------------

    def generate(self, request: SummaryGenerateRequest) -> dict[str, Any]:
        """Generate (or regenerate) and persist a summary for the request source."""
        transcript, context = self._resolve_transcript(request)
        draft, model = self._summarize(transcript)

        lead_id = self._resolve_lead_id(context)
        now = _utcnow()
        document: dict[str, Any] = {
            "conversation_id": context.get("conversation_id"),
            "lead_id": lead_id,
            "phone": context.get("phone"),
            "summary": draft.summary.strip(),
            "requirements": [item.strip() for item in draft.requirements if item and item.strip()],
            "objections": [item.strip() for item in draft.objections if item and item.strip()],
            "sentiment": draft.sentiment.value if isinstance(draft.sentiment, Sentiment) else str(draft.sentiment),
            "follow_up_actions": [
                item.strip() for item in draft.follow_up_actions if item and item.strip()
            ],
            "model": model,
            "updated_at": now,
        }

        call_id = context.get("call_id")
        if call_id:
            document["call_id"] = call_id
            existing = self._store.find_by_call(str(call_id))
            if existing:
                updated = self._store.update(existing["_id"], document)
                return updated or existing

        document["_id"] = str(uuid.uuid4())
        document["created_at"] = now
        self._store.insert(document)
        return document

    def list_summaries(self, **filters: Any) -> tuple[int, list[dict[str, Any]]]:
        """List summaries (thin pass-through to the store)."""
        return self._store.list_summaries(**filters)

    def get(self, summary_id: str) -> dict[str, Any] | None:
        """Fetch one summary by id."""
        return self._store.get(summary_id)
