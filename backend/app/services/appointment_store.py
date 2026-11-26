"""MongoDB-backed store for appointments.

One document per appointment is kept in the "appointments" collection, linked to
its lead and/or call. A unique index on a deterministic `dedupe_key` (customer
+ start minute) prevents two appointments being booked for the same customer in
the same time slot. Only appointment data is stored here - never credentials.

The connection is created lazily on first use, like the other stores.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.config import is_mongodb_uri_configured, settings

logger = logging.getLogger(__name__)

APPOINTMENTS_COLLECTION_NAME = "appointments"


class AppointmentStoreError(Exception):
    """Raised when appointments cannot be read from or written to MongoDB."""


class AppointmentDuplicateError(AppointmentStoreError):
    """Raised when an appointment already exists for the same customer and slot."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AppointmentStore:
    """Persists appointments in a MongoDB collection."""

    def __init__(self, uri: str | None = None, db_name: str | None = None) -> None:
        self._uri = uri if uri is not None else settings.MONGODB_URI
        self._db_name = db_name or settings.MONGODB_DB_NAME
        self._client: MongoClient | None = None
        self._indexes_ready = False

    def _collection(self):
        """Return the appointments collection, connecting to MongoDB on first use."""
        if self._client is None:
            if not is_mongodb_uri_configured(self._uri):
                raise AppointmentStoreError(
                    "MONGODB_URI is not configured on the server. Add a valid "
                    "MongoDB connection string to backend/.env and restart the API."
                )
            self._client = MongoClient(self._uri.strip(), serverSelectionTimeoutMS=8000)
        collection = self._client[self._db_name][APPOINTMENTS_COLLECTION_NAME]
        if not self._indexes_ready:
            try:
                collection.create_index("dedupe_key", unique=True)
                self._indexes_ready = True
            except PyMongoError:
                self._indexes_ready = True
        return collection

    def insert(self, document: dict[str, Any]) -> None:
        """Insert a new appointment; raise AppointmentDuplicateError on a slot clash."""
        try:
            self._collection().insert_one(dict(document))
        except DuplicateKeyError as exc:
            raise AppointmentDuplicateError(
                "An appointment already exists for that customer at this time."
            ) from exc
        except PyMongoError as exc:  # noqa: BLE001 - any driver failure becomes a clean error
            logger.error("MongoDB appointment write failed (%s)", type(exc).__name__)
            raise AppointmentStoreError(
                "Could not save the appointment right now. Please try again."
            ) from exc

    def get(self, appointment_id: str) -> dict[str, Any] | None:
        """Return an appointment by id, or None when it does not exist."""
        try:
            return self._collection().find_one({"_id": (appointment_id or "").strip()})
        except PyMongoError as exc:  # noqa: BLE001
            logger.error("MongoDB appointment read failed (%s)", type(exc).__name__)
            raise AppointmentStoreError(
                "Could not load the appointment right now. Please try again."
            ) from exc

    def update(self, appointment_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Apply field changes and return the updated document (None when missing)."""
        updates = {key: value for key, value in changes.items() if value is not None}
        try:
            return self._collection().find_one_and_update(
                {"_id": (appointment_id or "").strip()},
                {"$set": {**updates, "updated_at": _utcnow()}},
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            raise AppointmentDuplicateError(
                "Another appointment already exists for that customer at this time."
            ) from exc
        except PyMongoError as exc:  # noqa: BLE001
            logger.error("MongoDB appointment update failed (%s)", type(exc).__name__)
            raise AppointmentStoreError(
                "Could not update the appointment right now. Please try again."
            ) from exc

    def list_appointments(
        self,
        *,
        lead_id: str | None = None,
        conversation_id: str | None = None,
        status: str | None = None,
        phone_normalized: str | None = None,
        upcoming_only: bool = False,
        limit: int = 50,
        skip: int = 0,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Return (total, page) of appointments matching the filters, soonest first."""
        filters: dict[str, Any] = {}
        if lead_id:
            filters["lead_id"] = lead_id
        if conversation_id:
            filters["conversation_id"] = conversation_id
        if status:
            filters["status"] = status
        if phone_normalized:
            filters["phone_normalized"] = phone_normalized
        if upcoming_only:
            filters["scheduled_at"] = {"$gte": _utcnow()}

        def _query():
            collection = self._collection()
            total = collection.count_documents(filters)
            cursor = (
                collection.find(filters)
                .sort("scheduled_at", 1)
                .skip(max(skip, 0))
                .limit(max(limit, 1))
            )
            return total, list(cursor)

        try:
            return _query()
        except PyMongoError as exc:  # noqa: BLE001
            logger.error("MongoDB appointment list failed (%s)", type(exc).__name__)
            raise AppointmentStoreError(
                "Could not list appointments right now. Please try again."
            ) from exc
