"""MongoDB-backed conversation store.

Conversations (their message history and the lead collected so far) are persisted
in MongoDB, so a conversation can be resumed after a server restart or from
another worker. Only conversation data is stored here - never API keys or other
application configuration.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.config import is_mongodb_uri_configured, settings
from app.schemas.agent import LEAD_FIELDS, LeadInfo

logger = logging.getLogger(__name__)

# MongoDB collection that holds one document per conversation.
COLLECTION_NAME = "conversations"
# Collection that records one document per Vapi voice call (call id -> conversation).
CALLS_COLLECTION_NAME = "calls"
# Collection used to remember processed webhook events (idempotency guard).
EVENTS_COLLECTION_NAME = "webhook_events"


class ConversationStoreError(Exception):
    """Raised when conversations cannot be read from or written to MongoDB."""


class ConversationNotFoundError(ConversationStoreError):
    """Raised when a supplied conversation id does not exist in the database."""


class CallStoreError(ConversationStoreError):
    """Raised when Vapi call records cannot be read from or written to MongoDB."""


@dataclass
class Conversation:
    """A single customer conversation: its message history and collected lead."""

    id: str
    history: list[dict[str, str]] = field(default_factory=list)
    lead: LeadInfo = field(default_factory=LeadInfo)

    @property
    def turn_count(self) -> int:
        """Number of customer messages exchanged so far."""
        return sum(1 for entry in self.history if entry["role"] == "user")


def _utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class ConversationStore:
    """Persists conversations in a MongoDB collection.

    The connection is created lazily on the first read or write, so the API can
    start even when the database is not reachable yet. Any database problem is
    reported as a ConversationStoreError (and unknown ids as a
    ConversationNotFoundError) so the API layer can map it to a clean HTTP error.
    """

    def __init__(self, uri: str | None = None, db_name: str | None = None) -> None:
        self._uri = uri if uri is not None else settings.MONGODB_URI
        self._db_name = db_name or settings.MONGODB_DB_NAME
        self._client: MongoClient | None = None

    def _collection(self):
        """Return the conversations collection, connecting to MongoDB on first use."""
        if self._client is None:
            if not is_mongodb_uri_configured(self._uri):
                raise ConversationStoreError(
                    "MONGODB_URI is not configured on the server. Add a valid "
                    "MongoDB connection string to backend/.env and restart the API."
                )
            # serverSelectionTimeoutMS keeps a broken connection from hanging a request.
            self._client = MongoClient(self._uri.strip(), serverSelectionTimeoutMS=8000)
        return self._client[self._db_name][COLLECTION_NAME]

    def get_or_create(self, conversation_id: str | None = None) -> Conversation:
        """Load a conversation by id, or start a new one when no id is supplied.

        A supplied id must already exist; an unknown id raises
        ConversationNotFoundError instead of silently starting a new conversation.
        """
        if conversation_id is None:
            return Conversation(id=str(uuid.uuid4()))

        try:
            document = self._collection().find_one({"_id": conversation_id})
        except PyMongoError as exc:  # noqa: BLE001 - any driver failure becomes a clean error
            logger.error("MongoDB read failed (%s)", type(exc).__name__)
            raise ConversationStoreError(
                "Could not load the conversation right now. Please try again."
            ) from exc

        if document is None:
            raise ConversationNotFoundError(f"Conversation '{conversation_id}' was not found.")

        return self._to_conversation(document)

    def save(self, conversation: Conversation) -> None:
        """Insert or update the conversation document.

        created_at is written once (on insert); updated_at is refreshed on every
        save. The conversation id is used as the document _id.
        """
        now = _utcnow()
        try:
            self._collection().update_one(
                {"_id": conversation.id},
                {
                    "$set": {
                        "messages": [dict(entry) for entry in conversation.history],
                        "lead": conversation.lead.model_dump(),
                        "updated_at": now,
                    },
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )
        except PyMongoError as exc:  # noqa: BLE001 - any driver failure becomes a clean error
            logger.error("MongoDB write failed (%s)", type(exc).__name__)
            raise ConversationStoreError(
                "Could not save the conversation right now. Please try again."
            ) from exc

    def ensure_exists(self, conversation_id: str) -> None:
        """Create an empty conversation document if the id does not exist yet.

        The voice adapter calls this for ids that originate from a phone call
        (the Vapi call id) rather than from an API client, so a first call can
        begin a conversation. The /api/agent/chat contract is unaffected: that
        path uses get_or_create() and still returns 404 for an unknown id.
        """
        conversation_id = (conversation_id or "").strip()
        if not conversation_id:
            raise ConversationStoreError("A conversation id is required.")
        now = _utcnow()
        try:
            # insert_one only; a duplicate key means the conversation already
            # exists, so an existing history is never overwritten.
            self._collection().insert_one(
                {
                    "_id": conversation_id,
                    "messages": [],
                    "lead": LeadInfo().model_dump(),
                    "created_at": now,
                    "updated_at": now,
                }
            )
        except DuplicateKeyError:
            return
        except PyMongoError as exc:  # noqa: BLE001 - any driver failure becomes a clean error
            logger.error("MongoDB write failed (%s)", type(exc).__name__)
            raise ConversationStoreError(
                "Could not start the conversation right now. Please try again."
            ) from exc

    @staticmethod
    def _to_conversation(document: dict[str, Any]) -> Conversation:
        """Turn a MongoDB document into a Conversation object."""
        history = [
            {"role": entry["role"], "text": entry["text"]}
            for entry in document.get("messages", [])
        ]
        stored_lead = document.get("lead") or {}
        lead = LeadInfo(**{field: stored_lead.get(field) for field in LEAD_FIELDS})
        return Conversation(id=document["_id"], history=history, lead=lead)


class CallStore:
    """Persists Vapi call metadata and processed webhook events in MongoDB.

    One document per call is stored in the "calls" collection, keyed by the Vapi
    call id, linking the call to its conversation and holding the phone number,
    direction, timestamps, transcript and summary. A separate "webhook_events"
    collection records processed events so a retried webhook is not applied twice.
    The connection is created lazily, exactly like ConversationStore.
    """

    def __init__(self, uri: str | None = None, db_name: str | None = None) -> None:
        self._uri = uri if uri is not None else settings.MONGODB_URI
        self._db_name = db_name or settings.MONGODB_DB_NAME
        self._client: MongoClient | None = None

    def _db(self):
        """Return the database handle, connecting to MongoDB on first use."""
        if self._client is None:
            if not is_mongodb_uri_configured(self._uri):
                raise CallStoreError(
                    "MONGODB_URI is not configured on the server. Add a valid "
                    "MongoDB connection string to backend/.env and restart the API."
                )
            self._client = MongoClient(self._uri.strip(), serverSelectionTimeoutMS=8000)
        return self._client[self._db_name]

    def record(self, call_id: str, **fields: Any) -> None:
        """Insert or update a call document; only the supplied fields change.

        Values set to None are ignored so a partial webhook (for example a
        status update) never erases data captured earlier in the call.
        """
        call_id = (call_id or "").strip()
        if not call_id:
            raise CallStoreError("A call id is required to record a call.")
        now = _utcnow()
        updates = {key: value for key, value in fields.items() if value is not None}
        try:
            self._db()[CALLS_COLLECTION_NAME].update_one(
                {"_id": call_id},
                {"$set": {**updates, "updated_at": now}, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
        except PyMongoError as exc:  # noqa: BLE001 - any driver failure becomes a clean error
            logger.error("MongoDB call write failed (%s)", type(exc).__name__)
            raise CallStoreError(
                "Could not save the call right now. Please try again."
            ) from exc

    def get(self, call_id: str) -> dict[str, Any] | None:
        """Return a stored call document, or None when it is not present."""
        try:
            return self._db()[CALLS_COLLECTION_NAME].find_one({"_id": (call_id or "").strip()})
        except PyMongoError as exc:  # noqa: BLE001 - any driver failure becomes a clean error
            logger.error("MongoDB call read failed (%s)", type(exc).__name__)
            raise CallStoreError(
                "Could not load the call right now. Please try again."
            ) from exc

    def list_calls(
        self,
        *,
        conversation_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        skip: int = 0,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Return (total, page) of call documents matching the filters, newest first."""
        filters: dict[str, Any] = {}
        if conversation_id:
            filters["conversation_id"] = conversation_id
        if status:
            filters["status"] = status

        def _query():
            collection = self._db()[CALLS_COLLECTION_NAME]
            total = collection.count_documents(filters)
            cursor = (
                collection.find(filters)
                .sort("created_at", -1)
                .skip(max(skip, 0))
                .limit(max(limit, 1))
            )
            return total, list(cursor)

        try:
            return _query()
        except PyMongoError as exc:  # noqa: BLE001 - any driver failure becomes a clean error
            logger.error("MongoDB call list failed (%s)", type(exc).__name__)
            raise CallStoreError(
                "Could not list calls right now. Please try again."
            ) from exc

    def mark_event_processed(self, event_key: str) -> bool:
        """Return True the first time an event is seen, False when it is a duplicate.

        Used to make webhook handling idempotent: Vapi retries a delivery when it
        does not receive a 2xx quickly, which would otherwise apply the same
        status/report twice.
        """
        try:
            self._db()[EVENTS_COLLECTION_NAME].insert_one(
                {"_id": event_key, "created_at": _utcnow()}
            )
            return True
        except DuplicateKeyError:
            return False
        except PyMongoError as exc:  # noqa: BLE001 - any driver failure becomes a clean error
            logger.error("MongoDB event write failed (%s)", type(exc).__name__)
            raise CallStoreError(
                "Could not record the webhook event right now. Please try again."
            ) from exc
