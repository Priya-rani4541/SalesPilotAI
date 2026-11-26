"""RAG knowledge base package.

Modules:
- ``pdf_loader``   : extract text from uploaded PDFs (pypdf)
- ``chunker``      : split text into overlapping chunks
- ``embeddings``   : Gemini embedding provider
- ``vector_store`` : FAISS index with persisted chunk metadata
- ``knowledge_base``: orchestration (ingest + retrieval)
- ``answerer``     : Gemini answer grounded in retrieved context
- ``errors``       : shared error hierarchy
"""

from app.services.rag.knowledge_base import KnowledgeBase

__all__ = ["KnowledgeBase"]
