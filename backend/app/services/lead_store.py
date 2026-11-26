"""MongoDB-backed store for CRM leads.

One document per lead is kept in the "leads" collection. Duplicate leads are
prevented by the normalized (digits-only) phone number: the lead service looks a
lead up by phone before inserting a new one. Only lead data is stored here -
never API keys or other application configuration.

The connection is created lazily on first use, exactly like ConversationStore,
so the API can start even when the database is not reachable yet.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError

from app.core.config import is_mongodb_uri_configured, settings

logger = logging.getLogger(__name__)

LEADS_COLLECTION_NAME = "leads"


class LeadStoreError(Exception):
    """Raised when leads cannot be read from or written to MongoDB."""


def _utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class LeadStore:
    """Persists CRM leads in a MongoDB collection.

    Any database problem is reported as a LeadStoreError so the API layer can
    map it to a clean HTTP error (503).
    """

    def __init__(self, uri: str | None = None, db_name: str | None = None) -> None:
        self._uri = uri if uri is not None else settings.MONGODB_URI
        self._db_name = db_name or settings.MONGODB_DB_NAME
        self._client: MongoClient | None = None

    def _collection(self):
        """Return the leads collection, connecting to MongoDB on first use."""
        if self._client is None:
            if not is_mongodb_uri_configured(self._uri):
                raise LeadStoreError(
                    "MONGODB_URI is not configured on the server. Add a valid "
                    "MongoDB connection string to backend/.env and restart the API."
                )
            self._client = MongoClient(self._uri.strip(), serverSelectionTimeoutMS=8000)
        return self._client[self._db_name][LEADS_COLLECTION_NAME]

    def _run(self, action, failure_message: str):
        """Run a database action, turning any driver error into a LeadStoreError."""
        try:
            return action()
        except PyMongoError as exc:  # noqa: BLE001 - any driver failure becomes a clean error
            logger.error("MongoDB lead operation failed (%s)", type(exc).__name__)
            raise LeadStoreError(failure_message) from exc

    def get(self, lead_id: str) -> dict[str, Any] | None:
        """Return a lead document by id, or None when it does not exist."""
        return self._run(
            lambda: self._collection().find_one({"_id": (lead_id or "").strip()}),
            "Could not load the lead right now. Please try again.",
        )

    def find_by_phone(self, phone_normalized: str) -> dict[str, Any] | None:
        """Return the lead with this normalized phone, or None when there is none."""
        phone_normalized = (phone_normalized or "").strip()
        if not phone_normalized:
            return None
        return self._run(
            lambda: self._collection().find_one({"phone_normalized": phone_normalized}),
            "Could not look up the lead right now. Please try again.",
        )

    def find_by_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Return the lead linked to this conversation, or None when there is none."""
        conversation_id = (conversation_id or "").strip()
        if not conversation_id:
            return None
        return self._run(
            lambda: self._collection().find_one({"conversation_ids": conversation_id}),
            "Could not look up the lead right now. Please try again.",
        )

    def insert(self, document: dict[str, Any]) -> None:
        """Insert a new lead document (its _id and timestamps must be set by the caller)."""
        self._run(
            lambda: self._collection().insert_one(dict(document)),
            "Could not save the lead right now. Please try again.",
        )

    def update(self, lead_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Apply field changes to a lead and return the updated document.

        Values set to None are ignored so a partial update never erases data.
        Returns None when the lead does not exist.
        """
        lead_id = (lead_id or "").strip()
        updates = {key: value for key, value in changes.items() if value is not None}
        if not updates:
            return self.get(lead_id)
        return self._run(
            lambda: self._collection().find_one_and_update(
                {"_id": lead_id},
                {"$set": {**updates, "updated_at": _utcnow()}},
                return_document=ReturnDocument.AFTER,
            ),
            "Could not update the lead right now. Please try again.",
        )

    def add_call(
        self,
        lead_id: str,
        entry: dict[str, Any],
        conversation_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Append a call-history entry to a lead, ignoring it if already present.

        The `call_ids` guard makes this idempotent, so a retried webhook does not
        duplicate the call in the lead's history.
        """
        call_id = str(entry.get("call_id") or "").strip()
        if not call_id:
            raise LeadStoreError("A call id is required to record call history.")
        now = _utcnow()
        add_to_set: dict[str, Any] = {"call_ids": call_id}
        if conversation_id:
            add_to_set["conversation_ids"] = conversation_id
        self._run(
            lambda: self._collection().update_one(
                {"_id": (lead_id or "").strip(), "call_ids": {"$ne": call_id}},
                {
                    "$push": {"call_history": entry},
                    "$addToSet": add_to_set,
                    "$set": {"updated_at": now},
                },
            ),
            "Could not save the call history right now. Please try again.",
        )
        return self.get(lead_id)

    def list_leads(
        self,
        *,
        interest_level: str | None = None,
        status: str | None = None,
        phone_normalized: str | None = None,
        query: str | None = None,
        limit: int = 50,
        skip: int = 0,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Return (total, page) of leads matching the filters, newest first."""
        filters: dict[str, Any] = {}
        if interest_level:
            filters["interest_level"] = interest_level
        if status:
            filters["status"] = status
        if phone_normalized:
            filters["phone_normalized"] = phone_normalized
        if query:
            pattern = {"$regex": re.escape(query), "$options": "i"}
            filters["$or"] = [
                {"name": pattern},
                {"phone": pattern},
                {"requirements": pattern},
                {"budget": pattern},
            ]

        def _query():
            collection = self._collection()
            total = collection.count_documents(filters)
            cursor = (
                collection.find(filters)
                .sort("updated_at", -1)
                .skip(max(skip, 0))
                .limit(max(limit, 1))
            )
            return total, list(cursor)

        return self._run(_query, "Could not list leads right now. Please try again.")
