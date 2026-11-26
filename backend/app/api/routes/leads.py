"""CRM endpoints for qualified leads.

- GET  /api/leads            : list leads (optional filters + paging)
- GET  /api/leads/{lead_id}  : view one lead
- PATCH /api/leads/{lead_id} : update one lead

Leads are created automatically when the sales agent collects enough details
(see LeadService); these endpoints read and manage what was stored.

The store is shared with the sales agent, so all reads and writes go to the same
MongoDB "leads" collection. Any database problem is reported as 503 and an
unknown lead id as 404. Invalid input (a bad interest level/status or an unknown
field) is rejected by FastAPI with 422 before the handler runs.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.schemas.lead import (
    InterestLevel,
    Lead,
    LeadListResponse,
    LeadStatus,
    LeadUpdateRequest,
)
from app.services.lead_service import LeadService, normalize_phone
from app.services.lead_store import LeadStore, LeadStoreError

router = APIRouter()

_store = LeadStore()
_service = LeadService(_store)


@router.get("", response_model=LeadListResponse, summary="List leads")
def list_leads(
    interest_level: Optional[InterestLevel] = Query(
        default=None, description="Filter by HOT / WARM / COLD."
    ),
    status: Optional[LeadStatus] = Query(
        default=None, description="Filter by pipeline status."
    ),
    phone: Optional[str] = Query(
        default=None, description="Filter by phone number (compared digits-only)."
    ),
    q: Optional[str] = Query(
        default=None, description="Free-text search over name, phone, requirements and budget."
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Page size."),
    skip: int = Query(default=0, ge=0, description="Number of leads to skip."),
) -> LeadListResponse:
    """Return leads matching the filters, newest first."""
    try:
        total, documents = _store.list_leads(
            interest_level=interest_level.value if interest_level else None,
            status=status.value if status else None,
            phone_normalized=normalize_phone(phone) if phone else None,
            query=(q or "").strip() or None,
            limit=limit,
            skip=skip,
        )
    except LeadStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    leads = [_service.to_lead(document) for document in documents]
    return LeadListResponse(total=total, count=len(leads), leads=leads)


@router.get("/{lead_id}", response_model=Lead, summary="View one lead")
def get_lead(lead_id: str) -> Lead:
    """Return a single lead by id."""
    try:
        document = _store.get(lead_id)
    except LeadStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=404, detail=f"Lead '{lead_id}' was not found.")
    return _service.to_lead(document)


@router.patch("/{lead_id}", response_model=Lead, summary="Update one lead")
def update_lead(lead_id: str, payload: LeadUpdateRequest) -> Lead:
    """Update the allowed fields of a lead (only the fields sent are changed)."""
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "interest_level" in changes:
        changes["interest_level"] = changes["interest_level"].value
    if "status" in changes:
        changes["status"] = changes["status"].value

    try:
        document = _store.update(lead_id, changes)
    except LeadStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=404, detail=f"Lead '{lead_id}' was not found.")
    return _service.to_lead(document)
