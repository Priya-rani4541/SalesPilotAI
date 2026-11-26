"""Pydantic models for the RAG knowledge base API."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentInfo(BaseModel):
    """One indexed document in the knowledge base."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Knowledge base document id.")
    filename: str = Field(description="Original file name of the uploaded PDF.")
    pages: int = Field(description="Number of pages extracted from the PDF.")
    chunks: int = Field(description="Number of text chunks indexed for this document.")
    created_at: Optional[str] = Field(default=None, description="When the document was indexed.")


class DocumentListResponse(BaseModel):
    """Response body for GET /api/knowledge/documents."""

    total: int
    documents: list[DocumentInfo]


class UploadResponse(BaseModel):
    """Response body for POST /api/knowledge/documents."""

    document: DocumentInfo
    message: str


class QueryRequest(BaseModel):
    """Request body for POST /api/knowledge/query."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(description="The customer's question.")
    top_k: Optional[int] = Field(
        default=None,
        ge=1,
        le=20,
        description="How many chunks to retrieve. Defaults to the server setting.",
    )

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be empty")
        return value


class SourceChunk(BaseModel):
    """A retrieved chunk used to ground an answer."""

    model_config = ConfigDict(extra="ignore")

    document_id: str
    filename: str
    chunk_index: int
    page: Optional[int] = None
    score: float = Field(description="Cosine similarity between the question and this chunk.")
    text: str


class QueryResponse(BaseModel):
    """Response body for POST /api/knowledge/query."""

    question: str
    answer: str
    found: bool = Field(description="True when relevant knowledge base context was used.")
    sources: list[SourceChunk] = Field(description="Chunks the answer was grounded in.")
    model: str = Field(description="Gemini model used to write the answer.")
