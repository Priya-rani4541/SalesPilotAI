"""Shared error types for the RAG knowledge base.

Keeping the hierarchy in one place lets the API layer map every RAG failure to a
single, clean HTTP status without leaking internal details. The statuses follow
the app-wide convention:

- ``RagDocumentError``      -> 400 (the uploaded file cannot be used)
- ``RagNotFoundError``      -> 404 (a requested resource does not exist)
- ``RagConfigurationError`` -> 503 (the server is missing required configuration)
- ``RagRateLimitError``     -> 429 (Gemini quota exceeded)
- ``RagUpstreamError``      -> 502 (Gemini or FAISS failed / returned junk)
"""


class RagError(Exception):
    """Base class for all knowledge base errors."""


class RagDocumentError(RagError):
    """The uploaded document could not be used (unreadable, encrypted or empty)."""


class RagNotFoundError(RagError):
    """A requested knowledge base resource does not exist."""


class RagConfigurationError(RagError):
    """The server is missing required RAG configuration (for example a Gemini key)."""


class RagRateLimitError(RagError):
    """Gemini rejected a request because the API quota was exceeded."""


class RagUpstreamError(RagError):
    """An upstream dependency (Gemini or FAISS) failed or returned unusable data."""
