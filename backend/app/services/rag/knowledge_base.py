"""Knowledge base: ingest PDFs into FAISS and retrieve the relevant chunks.

The orchestration is intentionally thin - each step lives in its own module:

    PDF bytes --pdf_loader--> per-page text --chunker--> chunks
              --embeddings--> vectors --vector_store--> FAISS index

A small JSON manifest records which documents were ingested so the knowledge
base can list them. Nothing here touches the sales agent, conversations or CRM.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.rag.chunker import split_text
from app.services.rag.embeddings import GeminiEmbedder
from app.services.rag.errors import RagDocumentError, RagUpstreamError
from app.services.rag.pdf_loader import extract_pdf_pages
from app.services.rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

DOCUMENTS_FILE_NAME = "documents.json"


def _utcnow_iso() -> str:
    """Return the current time as an ISO-8601 UTC string."""
    return datetime.now(timezone.utc).isoformat()


class KnowledgeBase:
    """Coordinates PDF extraction, chunking, embedding and FAISS retrieval."""

    def __init__(
        self,
        embedder: GeminiEmbedder | None = None,
        directory: Path | str | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> None:
        self._embedder = embedder or GeminiEmbedder()
        self._dir = Path(directory) if directory else settings.rag_storage_path
        self._chunk_size = int(chunk_size or settings.RAG_CHUNK_SIZE)
        self._chunk_overlap = int(chunk_overlap or settings.RAG_CHUNK_OVERLAP)
        self._store = VectorStore(self._dir, self._embedder.dimension)
        self._documents: list[dict[str, Any]] | None = None

    def _documents_path(self) -> Path:
        return self._dir / DOCUMENTS_FILE_NAME

    def _load_documents(self) -> list[dict[str, Any]]:
        """Return the document manifest, reading it from disk on first use."""
        if self._documents is not None:
            return self._documents
        path = self._documents_path()
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                self._documents = data if isinstance(data, list) else []
            except (OSError, ValueError) as exc:
                logger.warning("Could not read the knowledge base manifest (%s)", type(exc).__name__)
                self._documents = []
        else:
            self._documents = []
        return self._documents

    def _save_documents(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with self._documents_path().open("w", encoding="utf-8") as handle:
                json.dump(self._documents, handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            raise RagUpstreamError("Could not save the knowledge base manifest.") from exc

    def ingest_pdf(self, filename: str, data: bytes) -> dict[str, Any]:
        """Extract, chunk, embed and index a PDF. Returns its manifest entry."""
        pages = extract_pdf_pages(data)

        records: list[dict[str, Any]] = []
        for page_number, page_text in enumerate(pages, start=1):
            for chunk in split_text(page_text, self._chunk_size, self._chunk_overlap):
                records.append(
                    {
                        "document_id": "",  # filled in below
                        "filename": filename,
                        "chunk_index": len(records),
                        "page": page_number,
                        "text": chunk,
                    }
                )
        if not records:
            raise RagDocumentError("No usable text was found in the PDF to index.")

        document_id = str(uuid.uuid4())
        for record in records:
            record["document_id"] = document_id

        vectors = self._embedder.embed_documents([record["text"] for record in records])
        self._store.add(vectors, records)

        entry = {
            "id": document_id,
            "filename": filename,
            "pages": len(pages),
            "chunks": len(records),
            "created_at": _utcnow_iso(),
        }
        documents = self._load_documents()
        documents.append(entry)
        self._save_documents()

        logger.info("Indexed '%s' (%d pages, %d chunks)", filename, len(pages), len(records))
        return entry

    def list_documents(self) -> list[dict[str, Any]]:
        """Return the manifest of indexed documents, newest first."""
        return list(reversed(self._load_documents()))

    def search(self, question: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """Return the chunks most similar to ``question`` (with a ``score`` field)."""
        vector = self._embedder.embed_query(question)
        hits = self._store.search(vector, top_k or settings.RAG_TOP_K)
        return [{**chunk, "score": score} for chunk, score in hits]
