"""Gemini embedding provider for the RAG knowledge base.

Wraps ``google-genai`` so the rest of the app only deals with plain
``list[float]`` vectors and a small, clean error hierarchy.
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

# Gemini accepts a limited number of inputs per embedding request; batch to be safe.
_MAX_BATCH_SIZE = 100

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
        # The SDK defaults to the "v1" API; embeddings are served on "v1beta".
        _client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(api_version="v1beta"),
        )
    return _client


class GeminiEmbedder:
    """Turns text into vectors with the configured Gemini embedding model."""

    def __init__(self, model: str | None = None, dimension: int | None = None) -> None:
        self._model = model or settings.GEMINI_EMBEDDING_MODEL
        self._dimension = int(dimension or settings.RAG_EMBEDDING_DIMENSION)

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed document chunks (optimised for the retrieval-document task)."""
        return self._embed(texts, task_type="RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        """Embed a customer question (optimised for the retrieval-query task)."""
        vectors = self._embed([text], task_type="RETRIEVAL_QUERY")
        if not vectors:
            raise RagUpstreamError("The embedding service returned no vector.")
        return vectors[0]

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        """Embed every non-blank text, batching requests to the provider."""
        cleaned = [text for text in texts if text and text.strip()]
        if not cleaned:
            return []
        client = _get_client()
        vectors: list[list[float]] = []
        for start in range(0, len(cleaned), _MAX_BATCH_SIZE):
            batch = cleaned[start : start + _MAX_BATCH_SIZE]
            vectors.extend(self._embed_batch(client, batch, task_type))
        return vectors

    def _embed_batch(
        self, client: genai.Client, batch: list[str], task_type: str
    ) -> list[list[float]]:
        """Embed one batch, mapping SDK failures to the RAG error hierarchy."""
        try:
            result = client.models.embed_content(
                model=self._model,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=self._dimension,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - any SDK failure becomes a clean error
            logger.error("Gemini embedding request failed (%s)", type(exc).__name__)
            if getattr(exc, "code", None) == 429:
                raise RagRateLimitError(
                    "The embedding service is rate limited right now. "
                    "Please retry in a moment."
                ) from exc
            raise RagUpstreamError(
                "The embedding service is currently unavailable. Please try again."
            ) from exc

        embeddings = list(getattr(result, "embeddings", None) or [])
        if len(embeddings) != len(batch):
            logger.error(
                "Gemini returned %d embeddings for %d inputs", len(embeddings), len(batch)
            )
            raise RagUpstreamError("The embedding service returned an unexpected response.")

        vectors: list[list[float]] = []
        for embedding in embeddings:
            values = list(getattr(embedding, "values", None) or [])
            if len(values) != self._dimension:
                logger.error(
                    "Embedding size %d does not match the configured dimension %d",
                    len(values),
                    self._dimension,
                )
                raise RagUpstreamError(
                    "The embedding service returned vectors of an unexpected size."
                )
            vectors.append(values)
        return vectors
