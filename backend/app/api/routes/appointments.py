"""Appointment booking endpoints.

- POST  /api/appointments           : book an appointment (validated + persisted)
- GET   /api/appointments           : list appointments (optional filters + paging)
- GET   /api/appointments/{id}      : view one appointment
- PATCH /api/appointments/{id}      : update / cancel / complete an appointment

A booking is only reported back once it has been saved to MongoDB. Two bookings
for the same customer and start minute are rejected with 409. Invalid input
(a past time, missing customer link) returns 422 and an unknown lead/appointment
returns 404.
"""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.schemas.appointment import (
    Appointment,
    AppointmentCreateRequest,
    AppointmentListResponse,
    AppointmentStatus,
    AppointmentUpdateRequest,
)
from app.services.appointment_service import (
    AppointmentConflictError,
    AppointmentNotFoundError,
    AppointmentService,
    AppointmentValidationError,
)
from app.services.appointment_store import AppointmentStoreError
from app.services.lead_service import normalize_phone

router = APIRouter()

_service = AppointmentService()


def _to_appointment(document: dict[str, Any]) -> Appointment:
    """Map a MongoDB appointment document to the API model (_id -> id)."""
    data = dict(document)
    data["id"] = data.pop("_id", data.get("id"))
    return Appointment(**data)


def _map_error(exc: Exception) -> HTTPException:
    """Translate an appointment error into a clean HTTP response."""
    if isinstance(exc, AppointmentValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, AppointmentNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AppointmentConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    raise HTTPException(status_code=503, detail=str(exc))


@router.post("", response_model=Appointment, status_code=201, summary="Book an appointment")
def create_appointment(payload: AppointmentCreateRequest) -> Appointment:
    """Validate and persist a new appointment."""
    try:
        document = _service.create(payload)
    except (AppointmentValidationError, AppointmentNotFoundError, AppointmentConflictError) as exc:
        raise _map_error(exc) from exc
    except AppointmentStoreError as exc:
        raise _map_error(exc) from exc
    return _to_appointment(document)


@router.get("", response_model=AppointmentListResponse, summary="List appointments")
def list_appointments(
    lead_id: Optional[str] = Query(default=None, description="Filter by lead id."),
    conversation_id: Optional[str] = Query(default=None, description="Filter by conversation id."),
    status: Optional[AppointmentStatus] = Query(default=None, description="Filter by status."),
    phone: Optional[str] = Query(default=None, description="Filter by phone (digits-only compare)."),
    upcoming: bool = Query(default=False, description="Only appointments from now onwards."),
    limit: int = Query(default=50, ge=1, le=200, description="Page size."),
    skip: int = Query(default=0, ge=0, description="Number of appointments to skip."),
) -> AppointmentListResponse:
    """Return appointments matching the filters, soonest first."""
    try:
        total, documents = _service.list_appointments(
            lead_id=lead_id,
            conversation_id=conversation_id,
            status=status.value if status else None,
            phone_normalized=normalize_phone(phone) if phone else None,
            upcoming_only=upcoming,
            limit=limit,
            skip=skip,
        )
    except AppointmentStoreError as exc:
        raise _map_error(exc) from exc

    appointments = [_to_appointment(document) for document in documents]
    return AppointmentListResponse(total=total, count=len(appointments), appointments=appointments)


@router.get("/{appointment_id}", response_model=Appointment, summary="View one appointment")
def get_appointment(appointment_id: str) -> Appointment:
    """Return a single appointment by id."""
    try:
        document = _service.get(appointment_id)
    except AppointmentStoreError as exc:
        raise _map_error(exc) from exc

    if document is None:
        raise HTTPException(
            status_code=404, detail=f"Appointment '{appointment_id}' was not found."
        )
    return _to_appointment(document)


@router.patch("/{appointment_id}", response_model=Appointment, summary="Update an appointment")
def update_appointment(appointment_id: str, payload: AppointmentUpdateRequest) -> Appointment:
    """Update, cancel or complete an appointment (only the fields sent are changed)."""
    try:
        document = _service.update(appointment_id, payload)
    except (AppointmentValidationError, AppointmentNotFoundError, AppointmentConflictError) as exc:
        raise _map_error(exc) from exc
    except AppointmentStoreError as exc:
        raise _map_error(exc) from exc
    return _to_appointment(document)
