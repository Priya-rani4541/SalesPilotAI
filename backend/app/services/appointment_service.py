"""Appointment booking logic: validation, link-to-customer, and duplicate prevention.

An appointment is only reported as booked after it has been saved to MongoDB.
Two appointments cannot be booked for the same customer in the same start minute
(a deterministic `dedupe_key` is enforced by a unique index); cancelling an
appointment frees its slot again.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.schemas.appointment import AppointmentCreateRequest, AppointmentStatus, AppointmentUpdateRequest
from app.services.appointment_store import (
    AppointmentDuplicateError,
    AppointmentStore,
)
from app.services.conversation_store import CallStore
from app.services.lead_service import normalize_phone
from app.services.lead_store import LeadStore

logger = logging.getLogger(__name__)


class AppointmentError(Exception):
    """Base class for appointment errors."""


class AppointmentValidationError(AppointmentError):
    """The supplied appointment data is invalid (for example, a past time)."""


class AppointmentNotFoundError(AppointmentError):
    """A referenced lead or appointment does not exist."""


class AppointmentConflictError(AppointmentError):
    """An appointment already exists for that customer and time slot."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc(value: datetime) -> datetime:
    """Normalise a datetime to timezone-aware UTC (naive values are assumed UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _slot_key(value: datetime) -> str:
    """A minute-resolution key used for duplicate-slot detection."""
    return value.strftime("%Y-%m-%dT%H:%M")


class AppointmentService:
    """Creates, updates and reads appointments, linking them to leads and calls."""

    def __init__(
        self,
        store: AppointmentStore | None = None,
        leads: LeadStore | None = None,
        calls: CallStore | None = None,
    ) -> None:
        self._store = store or AppointmentStore()
        self._leads = leads or LeadStore()
        self._calls = calls or CallStore()

    def _dedupe_key(self, scheduled_at: datetime, lead_id: str | None, phone_normalized: str) -> str:
        owner = lead_id or phone_normalized or "unknown"
        return f"{_slot_key(scheduled_at)}|{owner}"

    def _resolve_lead(self, lead_id: str | None, phone: str | None) -> tuple[str | None, str | None]:
        """Return (lead_id, lead_phone) resolving a phone to an existing lead when possible."""
        if lead_id:
            lead = self._leads.get(lead_id)
            if lead is None:
                raise AppointmentNotFoundError(f"Lead '{lead_id}' was not found.")
            return lead.get("_id"), lead.get("phone")
        phone_normalized = normalize_phone(phone)
        if phone_normalized:
            lead = self._leads.find_by_phone(phone_normalized)
            if lead:
                return lead.get("_id"), lead.get("phone") or phone
        return None, phone

    def create(self, request: AppointmentCreateRequest) -> dict[str, Any]:
        """Validate and persist a new appointment, returning the stored document."""
        scheduled_at = _to_utc(request.scheduled_at)
        if scheduled_at <= _utcnow():
            raise AppointmentValidationError("scheduled_at must be in the future.")

        lead_id, lead_phone = self._resolve_lead(request.lead_id, request.phone)
        phone = request.phone or lead_phone
        phone_normalized = normalize_phone(phone)
        if not lead_id and not phone_normalized:
            raise AppointmentValidationError("A valid lead_id or phone is required.")

        # Fill call/conversation context from the call when it was not supplied.
        call_id = request.call_id
        conversation_id = request.conversation_id
        if call_id:
            call = self._calls.get(call_id)
            if call is None:
                raise AppointmentNotFoundError(f"Call '{call_id}' was not found.")
            conversation_id = conversation_id or call.get("conversation_id")
            phone = phone or call.get("phone_number")
            phone_normalized = phone_normalized or normalize_phone(phone)

        now = _utcnow()
        document: dict[str, Any] = {
            "_id": str(uuid.uuid4()),
            "lead_id": lead_id,
            "call_id": call_id,
            "conversation_id": conversation_id,
            "phone": phone,
            "phone_normalized": phone_normalized,
            "customer_name": request.customer_name,
            "title": request.title,
            "notes": request.notes,
            "scheduled_at": scheduled_at,
            "duration_minutes": request.duration_minutes,
            "status": AppointmentStatus.SCHEDULED.value,
            "dedupe_key": self._dedupe_key(scheduled_at, lead_id, phone_normalized),
            "created_at": now,
            "updated_at": now,
        }
        try:
            self._store.insert(document)
        except AppointmentDuplicateError as exc:
            raise AppointmentConflictError(str(exc)) from exc
        return document

    def update(self, appointment_id: str, request: AppointmentUpdateRequest) -> dict[str, Any]:
        """Update an appointment, revalidating the slot when the time changes."""
        existing = self._store.get(appointment_id)
        if existing is None:
            raise AppointmentNotFoundError(f"Appointment '{appointment_id}' was not found.")

        changes = request.model_dump(exclude_unset=True, exclude_none=True)

        lead_id = existing.get("lead_id")
        phone_normalized = existing.get("phone_normalized") or ""
        cancelled = False

        if "scheduled_at" in changes:
            scheduled_at = _to_utc(changes["scheduled_at"])
            if scheduled_at <= _utcnow():
                raise AppointmentValidationError("scheduled_at must be in the future.")
            changes["scheduled_at"] = scheduled_at

        if "status" in changes:
            status = changes["status"]
            changes["status"] = status.value if isinstance(status, AppointmentStatus) else status
            cancelled = changes["status"] == AppointmentStatus.CANCELLED.value

        # Recompute the dedupe key from the (possibly new) time and owner; a
        # cancelled appointment frees its slot so it can be rebooked.
        scheduled_at = changes.get("scheduled_at", existing.get("scheduled_at"))
        if cancelled:
            changes["dedupe_key"] = f"cancelled:{appointment_id}"
        else:
            changes["dedupe_key"] = self._dedupe_key(scheduled_at, lead_id, phone_normalized)

        try:
            updated = self._store.update(appointment_id, changes)
        except AppointmentDuplicateError as exc:
            raise AppointmentConflictError(str(exc)) from exc
        if updated is None:
            raise AppointmentNotFoundError(f"Appointment '{appointment_id}' was not found.")
        return updated

    def get(self, appointment_id: str) -> dict[str, Any] | None:
        """Fetch one appointment by id."""
        return self._store.get(appointment_id)

    def list_appointments(self, **filters: Any) -> tuple[int, list[dict[str, Any]]]:
        """List appointments (thin pass-through to the store)."""
        return self._store.list_appointments(**filters)
