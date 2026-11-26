from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env from the backend directory (not the current working directory) so
# the file is found no matter where uvicorn is started from.
BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


def is_mongodb_uri_configured(uri: str | None) -> bool:
    """Return True when uri looks like a usable MongoDB connection string.

    Only the shape of the value is checked (the scheme is present and no unfilled
    "<...>" template placeholder remains). The value itself is never logged or
    returned, so credentials stay private.
    """
    uri = (uri or "").strip()
    return uri.startswith(("mongodb://", "mongodb+srv://")) and "<" not in uri and ">" not in uri


class Settings(BaseSettings):
    """Application settings loaded from environment variables / the .env file."""

    APP_NAME: str = "SalesPilot AI"
    APP_VERSION: str = "0.1.0"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS: comma-separated list of allowed frontend origins.
    CORS_ORIGINS: str = "http://localhost:5173"

    # Database (MongoDB Atlas)
    MONGODB_URI: str = ""
    MONGODB_DB_NAME: str = "salespilot"

    # AI (Google Gemini)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_TEMPERATURE: float = 0.4

    # RAG knowledge base
    # Embedding model (Gemini). Use a current model; text-embedding-004 is retired.
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"
    # Output vector size requested from the embedding model (Matryoshka-truncated).
    RAG_EMBEDDING_DIMENSION: int = 768
    # Chunking: target characters per chunk and overlap between neighbours.
    RAG_CHUNK_SIZE: int = 1000
    RAG_CHUNK_OVERLAP: int = 150
    # Retrieval: how many chunks to fetch and the minimum similarity to trust.
    # 0.50 sits between observed unrelated (~0.42-0.48) and related (~0.54-0.65)
    # gemini-embedding-001 cosine scores.
    RAG_TOP_K: int = 4
    RAG_MIN_SCORE: float = 0.50
    # Where the FAISS index and document manifest are stored. Empty uses
    # backend/data/knowledge_base (kept out of git).
    RAG_DATA_DIR: str = ""

    # Voice (Vapi)
    VAPI_API_KEY: str = ""
    VAPI_PHONE_NUMBER_ID: str = ""
    VAPI_ASSISTANT_ID: str = ""
    # Label sent back to Vapi for the Custom LLM model used to drive Gemini.
    VAPI_LLM_MODEL_NAME: str = "salespilot-gemini"
    # Shared secret that protects the Vapi endpoints (sent as x-vapi-secret).
    VAPI_WEBHOOK_SECRET: str = ""
    # Public HTTPS base URL where Vapi can reach this backend (use a tunnel in dev).
    PUBLIC_BASE_URL: str = ""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse the comma-separated CORS_ORIGINS value into a list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def mongodb_configured(self) -> bool:
        """True when MONGODB_URI is set to a usable value (the value is never exposed)."""
        return is_mongodb_uri_configured(self.MONGODB_URI)

    @property
    def vapi_configured(self) -> bool:
        """True when Vapi has enough configuration to place outbound calls.

        Only booleans are derived here; secret values are never logged or returned.
        """
        return bool(self.VAPI_API_KEY.strip() and self.VAPI_PHONE_NUMBER_ID.strip())

    @property
    def vapi_secret_configured(self) -> bool:
        """True when a shared secret is set to protect the Vapi endpoints."""
        return bool(self.VAPI_WEBHOOK_SECRET.strip())

    @property
    def rag_storage_path(self) -> Path:
        """Directory holding the FAISS index and the document manifest."""
        if self.RAG_DATA_DIR.strip():
            return Path(self.RAG_DATA_DIR.strip()).expanduser()
        return BACKEND_DIR / "data" / "knowledge_base"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


settings = get_settings()
