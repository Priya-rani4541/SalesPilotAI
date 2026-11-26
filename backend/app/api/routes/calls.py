"""Read-only call history endpoints used by the dashboard.

- GET /api/calls            : list stored Vapi calls (optional filters + paging)
- GET /api/calls/{call_id}  : view one call, including its transcript and summary

Calls are written by the Vapi webhook (see app/services/vapi_service.py); these
endpoints only read what was stored. An unknown call id returns 404 and a
database problem returns 503.
"""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.schemas.call import CallListResponse, CallRecord
from app.services.conversation_store import CallStore, CallStoreError

router = APIRouter()

_store = CallStore()


def _to_call(document: dict[str, Any]) -> CallRecord:
    """Map a MongoDB call document to the API model (_id -> id)."""
    data = dict(document)
    data["id"] = data.pop("_id", data.get("id"))
    return CallRecord(**data)


@router.get("", response_model=CallListResponse, summary="List calls")
def list_calls(
    conversation_id: Optional[str] = Query(default=None, description="Filter by conversation id."),
    status: Optional[str] = Query(default=None, description="Filter by call status."),
    limit: int = Query(default=50, ge=1, le=200, description="Page size."),
    skip: int = Query(default=0, ge=0, description="Number of calls to skip."),
) -> CallListResponse:
    """Return stored calls matching the filters, newest first."""
    try:
        total, documents = _store.list_calls(
            conversation_id=conversation_id, status=status, limit=limit, skip=skip
        )
    except CallStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    calls = [_to_call(document) for document in documents]
    return CallListResponse(total=total, count=len(calls), calls=calls)


@router.get("/{call_id}", response_model=CallRecord, summary="View one call")
def get_call(call_id: str) -> CallRecord:
    """Return a single call by id."""
    try:
        document = _store.get(call_id)
    except CallStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=404, detail=f"Call '{call_id}' was not found.")
    return _to_call(document)
