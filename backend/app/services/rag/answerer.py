"""Answer a customer question using ONLY the retrieved knowledge base context.

If no context is supplied the caller should show the fallback message without
calling Gemini at all; when context is supplied, the model is instructed to
answer from it alone and to fall back to the same message when the answer is
not covered.
"""

import logging

from google import genai
from google.genai import types

from app.core.config import settings
from app.services.rag.errors import (
    RagConfigurationError,
    RagRateLimitError,
    RagUpstreamError,
)

logger = logging.getLogger(__name__)

# Shown when the knowledge base has no relevant context, or the model cannot
# find the answer in it. Kept here so both paths return the same wording.
FALLBACK_ANSWER = (
    "I'm sorry, I don't have that information right now. "
    "Let me connect you with a specialist who can help."
)

SYSTEM_PROMPT = """You are a helpful sales assistant for SalesPilot AI.

# How to answer
- Answer the customer's question using ONLY the context provided below.
- Do not use any outside knowledge and never invent facts, prices, features,
  timelines, discounts or guarantees.
- If the context does not contain the answer, reply with exactly this sentence:
  "{fallback}"
- Keep the answer short, clear and friendly. Reply in the language the customer
  used (English, Hindi or Hinglish).

# Context
{context}"""

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Create the Gemini client once and reuse it."""
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY.strip():
            raise RagConfigurationError(
                "GEMINI_API_KEY is not configured on the server. "
                "Add it to backend/.env and restart the API."
            )
        _client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(api_version="v1beta"),
        )
    return _client


def build_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a numbered, citable context block."""
    parts: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        location = chunk.get("filename") or "document"
        if chunk.get("page"):
            location = f"{location}, page {chunk['page']}"
        parts.append(f"[{index}] ({location})\n{chunk.get('text', '')}")
    return "\n\n".join(parts)


def answer_question(question: str, chunks: list[dict]) -> str:
    """Return an answer grounded strictly in the retrieved chunks."""
    if not chunks:
        return FALLBACK_ANSWER

    client = _get_client()
    try:
        result = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=question,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT.format(
                    fallback=FALLBACK_ANSWER, context=build_context(chunks)
                ),
                temperature=settings.GEMINI_TEMPERATURE,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - any SDK failure becomes a clean error
        logger.error("Gemini answer request failed (%s)", type(exc).__name__)
        if getattr(exc, "code", None) == 429:
            raise RagRateLimitError(
                "The AI service is rate limited right now. Please retry in a moment."
            ) from exc
        raise RagUpstreamError(
            "The AI service is currently unavailable. Please try again."
        ) from exc

    answer = (getattr(result, "text", None) or "").strip()
    if not answer:
        logger.error("Gemini returned an empty answer")
        raise RagUpstreamError("The AI service returned an empty answer.")
    return answer
