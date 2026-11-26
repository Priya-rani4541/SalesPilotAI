"""Gemini-powered sales conversation engine.

The agent keeps the conversation history, collects lead details and always
returns structured output (a natural language reply plus the lead fields).
"""

import logging

from google import genai
from google.genai import types

from app.core.config import settings
from app.schemas.agent import LEAD_FIELDS, AgentTurn, LeadInfo
from app.services.conversation_store import Conversation, ConversationStore

logger = logging.getLogger(__name__)


class AgentError(Exception):
    """Base class for sales agent errors."""


class AgentConfigurationError(AgentError):
    """The server is missing a valid Gemini configuration."""


class AgentUpstreamError(AgentError):
    """Gemini could not be reached or returned an unusable response."""


class AgentRateLimitError(AgentError):
    """Gemini rejected the request because the API quota was exceeded."""


SYSTEM_PROMPT = """You are Ava, a professional sales consultant for SalesPilot AI.
SalesPilot AI provides an autonomous AI sales voice agent that helps businesses
qualify leads and handle sales conversations over the phone.

# Your goals
1. Be warm, professional and concise. Sound like a helpful human consultant, not a robot.
2. Understand what the customer needs and answer their questions clearly.
3. Collect these five lead details over the course of the conversation:
   - name: the customer's full name
   - phone: a contact phone number
   - budget: the budget they have in mind
   - product_interest: which product or use case they are interested in
   - purchase_timeline: when they plan to buy or get started

# How to talk
- Ask for at most one or two missing details per reply.
- Never ask again for a detail the customer has already given you.
- Keep replies short (one to three sentences) and conversational.
- Briefly acknowledge what the customer said before asking your next question.
- Once all five details are collected, thank the customer and let them know a
  specialist will follow up shortly.

# Rules
- NEVER invent products, prices, discounts, features, timelines or guarantees. If you
  do not know something, say so and offer to have a specialist follow up.
- Only fill a lead field when the customer has explicitly provided it; use null otherwise.
- Never guess or make up a name, phone number, budget or timeline.
- Reply in the language the customer uses. This conversation may run over a phone
  call, so speak naturally in English, Hindi, or Hinglish (mixed Hindi-English),
  mirroring the customer's language and script, and keep replies easy to say aloud.
- If the customer goes off topic, politely guide the conversation back to their needs.

# Output
Always reply with JSON that matches the given schema:
- "response": the natural language reply shown to the customer.
- "lead": all five lead fields collected so far (null for anything not yet provided).
"""

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Create the Gemini client once and reuse it."""
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY.strip():
            raise AgentConfigurationError(
                "GEMINI_API_KEY is not configured on the server. "
                "Add it to backend/.env and restart the API."
            )
        # The SDK defaults to the "v1" API, but system instructions (the sales
        # agent prompt) are only served on "v1beta".
        _client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(api_version="v1beta"),
        )
    return _client


def merge_lead(previous: LeadInfo, incoming: LeadInfo) -> LeadInfo:
    """Merge a newly returned lead with what we already knew.

    A value we already collected wins when the model returns nothing new, so a
    detail the customer gave earlier is never lost.
    """
    merged = {
        field: getattr(incoming, field) or getattr(previous, field) for field in LEAD_FIELDS
    }
    return LeadInfo(**merged)


def _build_contents(history: list[dict[str, str]], message: str) -> list[types.Content]:
    """Turn stored history plus the new customer message into Gemini contents."""
    contents = [
        types.Content(role=entry["role"], parts=[types.Part(text=entry["text"])])
        for entry in history
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))
    return contents


TRANSCRIPT_EXTRACTION_PROMPT = """You extract CRM lead details from a sales call transcript.

Read the transcript and return the five lead fields.
- "Customer:" lines are the customer; ignore what the agent said.
- Only fill a field when the customer explicitly stated it; use null otherwise.
- Never guess or invent a name, phone number, budget, interest or timeline."""


def extract_lead_from_transcript(transcript: str) -> LeadInfo | None:
    """Best-effort: pull the five lead fields out of a raw call transcript.

    Used as a fallback when a call's transcript exists but its conversation has
    no lead yet (for example a browser call that did not use the Custom LLM).
    Returns None on any failure so the caller keeps whatever it already has.
    """
    text = (transcript or "").strip()
    if not text:
        return None
    try:
        client = _get_client()
        result = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=TRANSCRIPT_EXTRACTION_PROMPT,
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=LeadInfo,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - extraction is a best-effort fallback
        logger.error("Transcript lead extraction failed (%s)", type(exc).__name__)
        return None
    return result.parsed if isinstance(result.parsed, LeadInfo) else None


def generate_turn(history: list[dict[str, str]], message: str) -> AgentTurn:
    """Ask Gemini for the next agent turn and validate the structured output."""
    client = _get_client()
    try:
        result = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=_build_contents(history, message),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=settings.GEMINI_TEMPERATURE,
                response_mime_type="application/json",
                response_schema=AgentTurn,
            ),
        )
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001 - any SDK failure becomes a clean API error
        logger.error("Gemini request failed (%s): %s", type(exc).__name__, exc)
        if getattr(exc, "code", None) == 429:
            raise AgentRateLimitError(
                "The AI service is rate limited right now. Please retry in a moment."
            ) from exc
        raise AgentUpstreamError(
            "The AI service is currently unavailable. Please try again."
        ) from exc

    turn = result.parsed
    if not isinstance(turn, AgentTurn):
        logger.error("Gemini returned a response that did not match the expected schema")
        raise AgentUpstreamError("The AI service returned an unexpected response.")

    return turn


class SalesAgent:
    """Runs one turn of a sales conversation and persists the updated state."""

    def __init__(self, store: ConversationStore) -> None:
        self._store = store

    def chat(self, message: str, conversation_id: str | None = None) -> tuple[Conversation, AgentTurn]:
        """Handle one customer message and return the conversation and agent turn."""
        conversation = self._store.get_or_create(conversation_id)

        # The pending message is only added to the stored history once Gemini has
        # replied, so a failed request cannot leave a dangling message behind.
        turn = generate_turn(conversation.history, message)
        conversation.history.append({"role": "user", "text": message})
        conversation.history.append({"role": "model", "text": turn.response})
        conversation.lead = merge_lead(conversation.lead, turn.lead)

        # Persist the updated history and lead so the conversation survives a restart.
        self._store.save(conversation)

        return conversation, turn
