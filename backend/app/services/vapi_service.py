"""Adapter that connects Vapi voice calls to the existing Gemini sales engine.

Vapi's Custom LLM feature posts an OpenAI-compatible chat request for every turn
of a call. This service:

- maps the Vapi call to a MongoDB conversation (the call id is used as the
  conversation id unless Vapi supplies `metadata.conversation_id`);
- runs the existing SalesAgent, which extracts the lead and persists the turn;
- returns only the natural-language reply, so the structured JSON wrapper is
  never spoken to the caller.

Webhook server messages are stored in the "calls" collection (phone number,
direction, status, timestamps, transcript, summary and metadata) and duplicate
deliveries are ignored.
"""

import json
import logging
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.schemas.summary import SummaryGenerateRequest
from app.schemas.vapi import VapiChatRequest, VapiCallRef
from app.services.conversation_store import (
    CallStore,
    Conversation,
    ConversationNotFoundError,
    ConversationStore,
)
from app.services.lead_service import LeadService, has_lead_signal
from app.services.sales_agent import SalesAgent, extract_lead_from_transcript, merge_lead
from app.services.summary_service import SummaryService, transcript_from_history

logger = logging.getLogger(__name__)

VAPI_CALLS_URL = "https://api.vapi.ai/call"


class VapiError(Exception):
    """Base class for Vapi integration errors."""


class VapiRequestError(VapiError):
    """Raised when a Vapi payload is missing something the backend requires."""


class VapiConfigurationError(VapiError):
    """Raised when the server is missing Vapi configuration it needs to act."""


class VapiUpstreamError(VapiError):
    """Raised when the Vapi REST API could not be reached or rejected the request."""


@dataclass
class VapiTurnResult:
    """The reply produced for one Vapi turn, plus where it was stored."""

    text: str
    conversation_id: str
    call_id: str
    model: str


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _direction_from_type(call_type: str | None) -> str | None:
    """Map Vapi's call type (e.g. outboundPhoneCall) to a simple direction."""
    if not call_type:
        return None
    lowered = call_type.lower()
    if "outbound" in lowered:
        return "outbound"
    if "inbound" in lowered:
        return "inbound"
    if "web" in lowered:
        return "web"
    return call_type


def _phone_from_customer(customer: Any) -> str | None:
    if isinstance(customer, dict):
        number = customer.get("number")
        if number:
            return str(number)
    return None


# Substrings in Vapi's endedReason that mean the call did not connect or broke
# down; anything else that ended is treated as a completed call.
_FAILED_END_HINTS = (
    "failed",
    "error",
    "no-answer",
    "no answer",
    "did-not-answer",
    "not-answered",
    "busy",
    "declined",
    "unreachable",
    "invalid-number",
)


def _status_from_end(message: dict[str, Any]) -> str:
    """Map a Vapi end-of-call report to a simple 'completed' / 'failed' status."""
    reason = str(message.get("endedReason") or message.get("status") or "").lower()
    if any(hint in reason for hint in _FAILED_END_HINTS):
        return "failed"
    return "completed"


def _extract_transcript(message: dict[str, Any], artifact: dict[str, Any]) -> str | None:
    """Pull a plain transcript out of an end-of-call report.

    Vapi normally sends a ready-made string on `transcript` (top level or under
    `artifact`). When only the structured `artifact.messages` array is present
    (common for browser/web calls) it is flattened into a "role: text" transcript.
    """
    transcript = message.get("transcript") or artifact.get("transcript")
    if isinstance(transcript, str) and transcript.strip():
        return transcript

    messages = artifact.get("messages") or message.get("messages")
    if isinstance(messages, list):
        lines: list[str] = []
        for entry in messages:
            if not isinstance(entry, dict):
                continue
            role = str(entry.get("role") or "").lower()
            speaker = "Agent" if role in ("assistant", "bot", "model", "ai") else "Customer"
            text = entry.get("message") or entry.get("content") or entry.get("text")
            if isinstance(text, str) and text.strip():
                lines.append(f"{speaker}: {text.strip()}")
        if lines:
            return "\n".join(lines)

    return transcript if isinstance(transcript, str) else None


def _post_json(url: str, body: dict[str, Any], api_key: str) -> dict[str, Any]:
    """POST JSON with a bearer token. The API key is never logged or returned."""
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read().decode("utf-8") or "{}"
            return json.loads(payload)
    except urllib.error.HTTPError as exc:
        # The body is not surfaced because it could echo request data.
        logger.error("Vapi API rejected the request (HTTP %s)", exc.code)
        raise VapiUpstreamError(
            f"Vapi rejected the outbound call (HTTP {exc.code})."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - any network failure becomes a clean error
        logger.error("Vapi API request failed (%s)", type(exc).__name__)
        raise VapiUpstreamError("Could not reach the Vapi API. Please try again.") from exc


class VapiService:
    """Runs Vapi turns on the existing engine and records call metadata."""

    def __init__(
        self,
        agent: SalesAgent,
        conversations: ConversationStore,
        calls: CallStore,
        leads: LeadService | None = None,
        summaries: SummaryService | None = None,
    ) -> None:
        self._agent = agent
        self._conversations = conversations
        self._calls = calls
        self._leads = leads
        self._summaries = summaries

    # --- conversation mapping -------------------------------------------------

    def resolve_conversation_id(self, call: VapiCallRef | None) -> str:
        """Return the conversation id for a call.

        A `metadata.conversation_id` supplied by the caller wins (used to keep
        one conversation across channels); otherwise the Vapi call id is used.
        """
        metadata = (call.metadata if call else None) or {}
        override = str(metadata.get("conversation_id") or "").strip()
        if override:
            return override
        call_id = str((call.id if call else "") or "").strip()
        if not call_id:
            raise VapiRequestError("The Vapi payload did not include a call id.")
        return call_id

    def _call_fields_from_ref(self, call: VapiCallRef | None) -> dict[str, Any]:
        if call is None:
            return {}
        return {
            "direction": _direction_from_type(call.type),
            "call_type": call.type,
            "phone_number": _phone_from_customer(call.customer),
            "vapi_metadata": call.metadata,
        }

    # --- Custom LLM turn ------------------------------------------------------

    def run_turn(self, request: VapiChatRequest) -> VapiTurnResult:
        """Handle one voice turn by delegating to the existing SalesAgent."""
        message = request.last_user_text()
        if not message:
            raise VapiRequestError("The Vapi payload did not include a user message.")

        call_id = str((request.call.id if request.call else "") or "").strip() or "unknown-call"
        conversation_id = self.resolve_conversation_id(request.call)

        # A phone call has no conversation yet: create it, then reuse the engine
        # (which loads the history, extracts the lead and persists the turn).
        self._conversations.ensure_exists(conversation_id)
        self._calls.record(call_id, conversation_id=conversation_id, **self._call_fields_from_ref(request.call))

        conversation, turn = self._agent.chat(message, conversation_id)

        # Persist the CRM lead and the running transcript as the call progresses,
        # so a browser/web call is visible in Leads and Calls even when no
        # end-of-call report (server message) is ever delivered.
        self._sync_lead_from_conversation(conversation)
        self._store_transcript(call_id, conversation)
        self._link_call_to_crm(call_id)

        return VapiTurnResult(
            text=turn.response,
            conversation_id=conversation.id,
            call_id=call_id,
            model=request.model or settings.VAPI_LLM_MODEL_NAME,
        )

    # --- webhook --------------------------------------------------------------

    def handle_webhook(self, message: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a Vapi server message and persist what it carries."""
        message_type = str(message.get("type") or "").strip()
        call = message.get("call") if isinstance(message.get("call"), dict) else {}
        call_id = str(call.get("id") or "").strip()

        if message_type == "assistant-request":
            return self._handle_assistant_request(call_id)

        if message_type == "tool-calls":
            # No tools are registered; acknowledge so Vapi does not retry.
            return {"results": []}

        if not call_id:
            logger.info("Vapi webhook '%s' had no call id; acknowledged.", message_type)
            return {"received": True}

        if message_type == "status-update":
            event_key = f"status-update:{call_id}:{message.get('status', '')}"
            if not self._calls.mark_event_processed(event_key):
                return {"received": True, "duplicate": True}
            self._record_status(call, message)
            return {"received": True}

        if message_type == "transcript":
            transcript = message.get("transcript")
            if transcript:
                self._calls.record(call_id, transcript=transcript)
            return {"received": True}

        if message_type == "end-of-call-report":
            event_key = f"end-of-call-report:{call_id}"
            if not self._calls.mark_event_processed(event_key):
                return {"received": True, "duplicate": True}
            self._record_end_of_call(call, message)
            return {"received": True}

        logger.info("Vapi webhook '%s' acknowledged without specific handling.", message_type)
        return {"received": True}

    def _handle_assistant_request(self, call_id: str) -> dict[str, Any]:
        """Answer Vapi's assistant-request with the configured assistant id."""
        assistant_id = settings.VAPI_ASSISTANT_ID.strip()
        logger.info(
            "Vapi assistant-request for call %s (assistant configured=%s)",
            call_id or "?",
            bool(assistant_id),
        )
        if assistant_id:
            return {"assistantId": assistant_id}
        # No assistant id configured: return an empty object so Vapi falls back to
        # the assistant already attached to the phone number.
        return {}

    def _record_status(self, call: dict[str, Any], message: dict[str, Any]) -> None:
        status = message.get("status")
        fields: dict[str, Any] = {
            "direction": _direction_from_type(call.get("type")),
            "call_type": call.get("type"),
            "phone_number": _phone_from_customer(call.get("customer")),
            "vapi_metadata": call.get("metadata"),
            "status": status,
        }
        started_at = message.get("startedAt") or call.get("startedAt")
        if status in ("in-progress", "ringing", "forwarding") and started_at:
            fields["started_at"] = started_at
        self._calls.record(str(call.get("id")), **fields)

    def _record_end_of_call(self, call: dict[str, Any], message: dict[str, Any]) -> None:
        artifact = message.get("artifact") if isinstance(message.get("artifact"), dict) else {}
        analysis = message.get("analysis") if isinstance(message.get("analysis"), dict) else {}
        self._calls.record(
            str(call.get("id")),
            direction=_direction_from_type(call.get("type")),
            call_type=call.get("type"),
            phone_number=_phone_from_customer(call.get("customer")),
            # Fall back to the call id: the Custom LLM turn uses it as the
            # conversation id, so this keeps the call linked to its conversation
            # (and therefore to the CRM lead) even when Vapi sends no metadata.
            conversation_id=(call.get("metadata") or {}).get("conversation_id")
            or str(call.get("id") or "").strip()
            or None,
            vapi_metadata=call.get("metadata"),
            status=_status_from_end(message),
            ended_reason=message.get("endedReason"),
            started_at=message.get("startedAt") or call.get("startedAt"),
            ended_at=message.get("endedAt") or call.get("endedAt") or _utcnow_iso(),
            transcript=_extract_transcript(message, artifact),
            summary=analysis.get("summary") or message.get("summary"),
            recording_url=artifact.get("recordingUrl") or message.get("recordingUrl"),
            cost=message.get("cost"),
            duration_seconds=message.get("durationSeconds"),
        )
        self._attach_lead(call)
        self._summarize_call(str(call.get("id") or ""))

    def _summarize_call(self, call_id: str) -> None:
        """Generate and store a call summary once the call has ended.

        Best effort: any failure (for example a Gemini quota error) is logged and
        swallowed so the webhook is never broken by summarisation.
        """
        if self._summaries is None or not call_id:
            return
        try:
            self._summaries.generate(SummaryGenerateRequest(call_id=call_id))
        except Exception as exc:  # noqa: BLE001 - summarisation must not break the webhook
            logger.warning("Call summary generation failed for %s (%s)", call_id, type(exc).__name__)

    def _attach_lead(self, call: dict[str, Any]) -> None:
        """Link a finished call (and its conversation lead) to the CRM.

        Best effort: the lead is synced from the conversation it belongs to and
        the call is appended to that lead's call history. Any failure is logged
        and swallowed so webhook handling is never broken by the CRM.
        """
        if self._leads is None:
            return
        call_id = str(call.get("id") or "").strip()
        if not call_id:
            return
        try:
            # Prefer the stored document: it holds the resolved conversation id
            # (and any explicit lead id), which the raw webhook may not carry.
            call_document = self._calls.get(call_id)
            conversation_id = ""
            if call_document:
                conversation_id = str(call_document.get("conversation_id") or "").strip()
            if not conversation_id:
                conversation_id = (
                    str((call.get("metadata") or {}).get("conversation_id") or "").strip()
                    or call_id
                )
            try:
                conversation = self._conversations.get_or_create(conversation_id)
                # If the conversation collected nothing (for example a native-model
                # browser call), fall back to extracting the lead from the transcript.
                if not has_lead_signal(conversation.lead):
                    transcript = (call_document or {}).get("transcript") or ""
                    extracted = extract_lead_from_transcript(transcript) if transcript else None
                    if extracted is not None and has_lead_signal(extracted):
                        conversation.lead = merge_lead(conversation.lead, extracted)
                        self._conversations.save(conversation)
                # allow_partial so a phone-less web call is still stored as a lead.
                self._leads.sync_from_conversation(conversation, allow_partial=True)
            except ConversationNotFoundError:
                pass
            if call_document:
                self._leads.attach_call(call_document)
        except Exception as exc:  # noqa: BLE001 - CRM sync must not break the webhook
            logger.error("Lead sync after call failed (%s)", type(exc).__name__)

    def _sync_lead_from_conversation(self, conversation: Conversation) -> None:
        """Keep the CRM in sync with a conversation while a call is running.

        Best effort: a browser/web call must still appear in Leads even when no
        end-of-call report (server message) is ever delivered. Any failure is
        logged and swallowed so the voice turn is never broken.
        """
        if self._leads is None:
            return
        try:
            self._leads.sync_from_conversation(conversation, allow_partial=True)
        except Exception as exc:  # noqa: BLE001 - CRM sync must not break the turn
            logger.warning("Lead sync during call failed (%s)", type(exc).__name__)

    def _store_transcript(self, call_id: str, conversation: Conversation) -> None:
        """Persist the running transcript on the call record (best effort)."""
        try:
            transcript = transcript_from_history(conversation.history)
            if transcript:
                self._calls.record(call_id, transcript=transcript)
        except Exception as exc:  # noqa: BLE001 - transcript storage must not break the turn
            logger.warning("Storing the call transcript failed (%s)", type(exc).__name__)

    def _link_call_to_crm(self, call_id: str) -> None:
        """Attach a stored call to its lead (best effort).

        Called right after an outbound call is created so the CRM shows the call
        while it is still in progress. Any failure is logged and swallowed.
        """
        if self._leads is None or not call_id:
            return
        try:
            call_document = self._calls.get(call_id)
            if call_document:
                self._leads.attach_call(call_document)
        except Exception as exc:  # noqa: BLE001 - CRM linking must not break the caller
            logger.error(
                "Linking outbound call %s to the CRM failed (%s)", call_id, type(exc).__name__
            )

    # --- outbound call --------------------------------------------------------

    def start_outbound_call(
        self,
        phone_number: str,
        conversation_id: str | None = None,
        assistant_id: str | None = None,
        lead_id: str | None = None,
        customer_name: str | None = None,
    ) -> dict[str, Any]:
        """Ask Vapi to place an outbound call and record it locally.

        Requires VAPI_API_KEY, VAPI_PHONE_NUMBER_ID and an assistant id. When a
        credential is missing the caller receives a clear 503 rather than a fake
        success, so untested paths are never reported as working.

        The number to dial is validated, an optional CRM lead is looked up (so a
        typo is rejected instead of silently creating a stray lead) and the call
        is linked to the CRM straight away, before it connects.
        """
        dial_number = (phone_number or "").strip()
        if len(re.sub(r"\D+", "", dial_number)) < 8:
            raise VapiRequestError("A dialable phone number is required.")

        # Validate the supplied lead before touching server configuration, so a
        # bad request is reported as such even when calling is not set up yet.
        resolved_lead = (lead_id or "").strip() or None
        if resolved_lead and self._leads is not None and self._leads.get_lead(resolved_lead) is None:
            raise VapiRequestError(f"Lead '{resolved_lead}' was not found.")

        api_key = settings.VAPI_API_KEY.strip()
        if not api_key:
            raise VapiConfigurationError(
                "VAPI_API_KEY is not configured on the server. Add it to backend/.env."
            )
        phone_number_id = settings.VAPI_PHONE_NUMBER_ID.strip()
        if not phone_number_id:
            raise VapiConfigurationError(
                "VAPI_PHONE_NUMBER_ID is not configured on the server. Add it to backend/.env."
            )
        resolved_assistant = (assistant_id or settings.VAPI_ASSISTANT_ID).strip()
        if not resolved_assistant:
            raise VapiRequestError(
                "A Vapi assistant id is required (set VAPI_ASSISTANT_ID or pass assistant_id)."
            )

        conversation = (conversation_id or "").strip() or str(uuid.uuid4())
        self._conversations.ensure_exists(conversation)

        # The engine reads metadata.conversation_id to keep one conversation
        # across channels and metadata.lead_id to link the CRM record.
        metadata: dict[str, Any] = {"conversation_id": conversation}
        if resolved_lead:
            metadata["lead_id"] = resolved_lead

        overrides: dict[str, Any] = {"metadata": metadata}
        greeting_name = (customer_name or "").strip()
        if greeting_name:
            overrides["variableValues"] = {"customer_name": greeting_name}

        body = {
            "phoneNumberId": phone_number_id,
            "assistantId": resolved_assistant,
            "customer": {"number": dial_number},
            "assistantOverrides": overrides,
        }
        response = _post_json(VAPI_CALLS_URL, body, api_key)

        call_id = str(response.get("id") or "").strip() or None
        status = response.get("status") or "queued"
        if call_id:
            self._calls.record(
                call_id,
                conversation_id=conversation,
                phone_number=dial_number,
                direction="outbound",
                call_type="outboundPhoneCall",
                status=status,
                lead_id=resolved_lead,
                vapi_metadata=metadata,
            )
            # Link the outbound call to its CRM lead immediately so the
            # dashboard shows the call while it is still in progress.
            self._link_call_to_crm(call_id)
        return {
            "call_id": call_id,
            "conversation_id": conversation,
            "status": status,
            "lead_id": resolved_lead,
        }
