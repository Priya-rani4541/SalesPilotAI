"""MongoDB-backed store for call summaries.

One summary document per call is kept in the "call_summaries" collection,
generated from the call transcript and linked to the call, conversation and lead.
Only summary data is stored here - never API keys or application configuration.

The connection is created lazily on first use, like the other stores, so the API
can start even when the database is not reachable yet.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError

from app.core.config import is_mongodb_uri_configured, settings

logger = logging.getLogger(__name__)

SUMMARIES_COLLECTION_NAME = "call_summaries"


class SummaryStoreError(Exception):
    """Raised when summaries cannot be read from or written to MongoDB."""


def _utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class SummaryStore:
    """Persists call summaries in a MongoDB collection."""

    def __init__(self, uri: str | None = None, db_name: str | None = None) -> None:
        self._uri = uri if uri is not None else settings.MONGODB_URI
        self._db_name = db_name or settings.MONGODB_DB_NAME
        self._client: MongoClient | None = None
        self._indexes_ready = False

    def _collection(self):
        """Return the summaries collection, connecting to MongoDB on first use."""
        if self._client is None:
            if not is_mongodb_uri_configured(self._uri):
                raise SummaryStoreError(
                    "MONGODB_URI is not configured on the server. Add a valid "
                    "MongoDB connection string to backend/.env and restart the API."
                )
            self._client = MongoClient(self._uri.strip(), serverSelectionTimeoutMS=8000)
        collection = self._client[self._db_name][SUMMARIES_COLLECTION_NAME]
        if not self._indexes_ready:
            # At most one summary per call; documents without a call id are simply
            # not covered by the partial index.
            try:
                collection.create_index(
                    "call_id",
                    unique=True,
                    partialFilterExpression={"call_id": {"$exists": True}},
                )
                self._indexes_ready = True
            except PyMongoError:
                # A concurrent creator or an existing index is fine; keep going.
                self._indexes_ready = True
        return collection

    def _run(self, action, failure_message: str):
        """Run a database action, turning any driver error into a SummaryStoreError."""
        try:
            return action()
        except PyMongoError as exc:  # noqa: BLE001 - any driver failure becomes a clean error
            logger.error("MongoDB summary operation failed (%s)", type(exc).__name__)
            raise SummaryStoreError(failure_message) from exc

    def get(self, summary_id: str) -> dict[str, Any] | None:
        """Return a summary document by id, or None when it does not exist."""
        return self._run(
            lambda: self._collection().find_one({"_id": (summary_id or "").strip()}),
            "Could not load the summary right now. Please try again.",
        )

    def find_by_call(self, call_id: str) -> dict[str, Any] | None:
        """Return the summary for a call, or None when there is none."""
        call_id = (call_id or "").strip()
        if not call_id:
            return None
        return self._run(
            lambda: self._collection().find_one({"call_id": call_id}),
            "Could not look up the summary right now. Please try again.",
        )

    def insert(self, document: dict[str, Any]) -> None:
        """Insert a new summary document (its _id and timestamps must be set)."""
        self._run(
            lambda: self._collection().insert_one(dict(document)),
            "Could not save the summary right now. Please try again.",
        )

    def update(self, summary_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Apply field changes to a summary and return the updated document."""
        updates = {key: value for key, value in changes.items() if value is not None}
        return self._run(
            lambda: self._collection().find_one_and_update(
                {"_id": (summary_id or "").strip()},
                {"$set": {**updates, "updated_at": _utcnow()}},
                return_document=ReturnDocument.AFTER,
            ),
            "Could not update the summary right now. Please try again.",
        )

    def list_summaries(
        self,
        *,
        call_id: str | None = None,
        conversation_id: str | None = None,
        lead_id: str | None = None,
        sentiment: str | None = None,
        limit: int = 50,
        skip: int = 0,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Return (total, page) of summaries matching the filters, newest first."""
        filters: dict[str, Any] = {}
        if call_id:
            filters["call_id"] = call_id
        if conversation_id:
            filters["conversation_id"] = conversation_id
        if lead_id:
            filters["lead_id"] = lead_id
        if sentiment:
            filters["sentiment"] = sentiment

        def _query():
            collection = self._collection()
            total = collection.count_documents(filters)
            cursor = (
                collection.find(filters)
                .sort("created_at", -1)
                .skip(max(skip, 0))
                .limit(max(limit, 1))
            )
            return total, list(cursor)

        return self._run(_query, "Could not list summaries right now. Please try again.")
