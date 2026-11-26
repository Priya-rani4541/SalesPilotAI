"""RAG knowledge base endpoints.

- POST /api/knowledge/documents : upload a PDF and index it into FAISS
- GET  /api/knowledge/documents : list the indexed documents
- POST /api/knowledge/query     : answer a question from the knowledge base only

The knowledge base is independent of the sales agent, conversations and CRM: it
only reads and writes its own FAISS index and manifest. Every RAG failure is
mapped to a clean HTTP error (400 / 404 / 429 / 502 / 503).
"""

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import settings
from app.schemas.knowledge import (
    DocumentInfo,
    DocumentListResponse,
    QueryRequest,
    QueryResponse,
    SourceChunk,
    UploadResponse,
)
from app.services.rag.answerer import FALLBACK_ANSWER, answer_question
from app.services.rag.errors import (
    RagConfigurationError,
    RagDocumentError,
    RagError,
    RagNotFoundError,
    RagRateLimitError,
)
from app.services.rag.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)

router = APIRouter()

_kb = KnowledgeBase()

# Reject oversized uploads before reading them into memory.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB


def _to_http_error(exc: Exception) -> HTTPException:
    """Map a RAG error onto the matching HTTP status."""
    if isinstance(exc, RagDocumentError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RagNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RagConfigurationError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, RagRateLimitError):
        return HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "60"})
    return HTTPException(status_code=502, detail=str(exc))


@router.post(
    "/documents",
    response_model=UploadResponse,
    status_code=201,
    summary="Upload and index a PDF",
)
def upload_document(file: UploadFile = File(...)) -> UploadResponse:
    """Extract, chunk, embed and index a PDF into the knowledge base."""
    filename = (file.filename or "").strip() or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"The PDF exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.",
        )

    try:
        entry = _kb.ingest_pdf(filename, data)
    except RagError as exc:
        logger.warning("Knowledge base ingestion failed (%s)", type(exc).__name__)
        raise _to_http_error(exc) from exc

    return UploadResponse(
        document=DocumentInfo(**entry),
        message=f"Indexed '{filename}' into the knowledge base.",
    )


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    summary="List indexed documents",
)
def list_documents() -> DocumentListResponse:
    """Return every document currently indexed in the knowledge base."""
    try:
        documents = _kb.list_documents()
    except RagError as exc:
        raise _to_http_error(exc) from exc

    items = [DocumentInfo(**document) for document in documents]
    return DocumentListResponse(total=len(items), documents=items)


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Answer a question from the knowledge base",
)
def query(payload: QueryRequest) -> QueryResponse:
    """Retrieve relevant chunks and answer using ONLY that business context.

    When nothing relevant is found (or every match is below the confidence
    threshold) a friendly "information unavailable" reply is returned without
    calling Gemini.
    """
    try:
        hits = _kb.search(payload.question, payload.top_k)
    except RagError as exc:
        logger.warning("Knowledge base retrieval failed (%s)", type(exc).__name__)
        raise _to_http_error(exc) from exc

    relevant = [hit for hit in hits if hit["score"] >= settings.RAG_MIN_SCORE]
    if not relevant:
        return QueryResponse(
            question=payload.question,
            answer=FALLBACK_ANSWER,
            found=False,
            sources=[],
            model=settings.GEMINI_MODEL,
        )

    try:
        answer = answer_question(payload.question, relevant)
    except RagError as exc:
        raise _to_http_error(exc) from exc

    return QueryResponse(
        question=payload.question,
        answer=answer,
        found=True,
        sources=[SourceChunk(**hit) for hit in relevant],
        model=settings.GEMINI_MODEL,
    )
