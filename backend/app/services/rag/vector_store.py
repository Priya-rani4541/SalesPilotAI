"""FAISS-backed vector store for knowledge base chunks.

A single flat index holds every chunk vector; a parallel list holds the chunk
metadata. Vectors are L2-normalised and searched with inner product, which is
equivalent to cosine similarity. The index and its metadata are persisted to
disk so the knowledge base survives a restart.

Only knowledge base data is stored here - never API keys or configuration.
"""

import logging
import pickle
import threading
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from app.services.rag.errors import RagUpstreamError

logger = logging.getLogger(__name__)

INDEX_FILE_NAME = "index.faiss"
CHUNKS_FILE_NAME = "chunks.pkl"


class VectorStore:
    """A cosine-similarity FAISS index with persisted, parallel chunk metadata."""

    def __init__(self, directory: Path, dimension: int) -> None:
        self._dir = Path(directory)
        self._dimension = int(dimension)
        self._index: faiss.Index | None = None
        self._chunks: list[dict[str, Any]] = []
        # Guard mutations (and the lazy load) so concurrent requests stay consistent.
        self._lock = threading.Lock()

    @property
    def size(self) -> int:
        """Number of chunk vectors currently stored."""
        return len(self._chunks)

    @property
    def dimension(self) -> int:
        return self._dimension

    def _index_path(self) -> Path:
        return self._dir / INDEX_FILE_NAME

    def _chunks_path(self) -> Path:
        return self._dir / CHUNKS_FILE_NAME

    def _load(self) -> None:
        """Load the index and metadata from disk once, on first use."""
        if self._index is not None:
            return

        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RagUpstreamError(
                "Could not create the knowledge base storage directory."
            ) from exc

        try:
            if self._index_path().exists():
                index = faiss.read_index(str(self._index_path()))
                if index.d != self._dimension:
                    raise RagUpstreamError(
                        "The stored knowledge base was built with a different "
                        "embedding size. Re-index the documents or restore the "
                        "previous embedding configuration."
                    )
                self._index = index
            else:
                self._index = faiss.IndexFlatIP(self._dimension)

            if self._chunks_path().exists():
                with self._chunks_path().open("rb") as handle:
                    loaded = pickle.load(handle)  # noqa: S301 - our own file
                self._chunks = list(loaded) if isinstance(loaded, list) else []
            else:
                self._chunks = []
        except RagUpstreamError:
            raise
        except Exception as exc:  # noqa: BLE001 - corruption becomes a clean error
            logger.error("Failed to load the FAISS index (%s)", type(exc).__name__)
            raise RagUpstreamError("Could not load the knowledge base index.") from exc

    def _to_matrix(self, vectors: list[list[float]]) -> np.ndarray:
        """Return an L2-normalised float32 matrix, validating the shape."""
        matrix = np.asarray(vectors, dtype="float32")
        if matrix.ndim != 2 or matrix.shape[1] != self._dimension:
            raise RagUpstreamError(
                "Embedding vectors have an unexpected shape for the knowledge base."
            )
        faiss.normalize_L2(matrix)
        return matrix

    def add(self, vectors: list[list[float]], chunks: list[dict[str, Any]]) -> None:
        """Append vectors and their metadata to the index, then persist."""
        if len(vectors) != len(chunks):
            raise RagUpstreamError("Vector and chunk counts do not match.")
        if not vectors:
            return

        with self._lock:
            self._load()
            self._index.add(self._to_matrix(vectors))
            self._chunks.extend(chunks)
            self._save()

    def search(self, vector: list[float], top_k: int) -> list[tuple[dict[str, Any], float]]:
        """Return up to ``top_k`` (chunk, cosine-score) pairs, best first."""
        with self._lock:
            self._load()
            if not self._chunks:
                return []
            query = self._to_matrix([vector])
            k = max(1, min(int(top_k), len(self._chunks)))
            scores, indices = self._index.search(query, k)

        results: list[tuple[dict[str, Any], float]] = []
        for score, position in zip(scores[0], indices[0]):
            if position < 0:
                continue
            results.append((self._chunks[int(position)], float(score)))
        return results

    def _save(self) -> None:
        """Persist the index and metadata to disk."""
        try:
            faiss.write_index(self._index, str(self._index_path()))
            with self._chunks_path().open("wb") as handle:
                pickle.dump(self._chunks, handle)
        except OSError as exc:
            raise RagUpstreamError("Could not persist the knowledge base index.") from exc
