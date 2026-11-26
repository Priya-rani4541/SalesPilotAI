"""Lead qualification and CRM sync.

This module turns what the sales agent collected (a conversation "lead") into a
CRM record, and links voice calls to that record.

Qualification is deterministic: the raw lead fields come from Gemini, but the
HOT/WARM/COLD decision is made here with fixed rules (contactability + how much
was answered + how soon the customer wants to buy), never by the model.
"""

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.schemas.agent import LEAD_FIELDS, LeadInfo
from app.schemas.lead import InterestLevel, Lead, LeadStatus
from app.services.conversation_store import Conversation
from app.services.lead_store import LeadStore

logger = logging.getLogger(__name__)

# Purchases timelines are bucketed with deterministic keyword rules. Hinglish
# hints are included because the agent supports English/Hindi/Hinglish.
_LONG_TERM_HINTS = (
    "next year",
    "no hurry",
    "not sure",
    "just looking",
    "just browsing",
    "someday",
    "some day",
    "6 months",
    "six months",
    "a year",
    "one year",
    "later",
    "abhi nahi",
    "sochna",
    "research",
    "comparing",
)
_IMMEDIATE_HINTS = (
    "asap",
    "as soon as possible",
    "immediately",
    "immediate",
    "right away",
    "right now",
    "today",
    "tomorrow",
    "this week",
    "within a week",
    "within a month",
    "within days",
    "this month",
    "urgent",
    "abhi",
    "aaj",
    "kal",
    "jaldi",
    "is hafte",
    "is mahine",
)
_NEAR_TERM_HINTS = (
    "next week",
    "next month",
    "within a month",
    "1 month",
    "one month",
    "two months",
    "2 months",
    "3 months",
    "three months",
    "few months",
    "this quarter",
    "soon",
    "agle mahine",
    "agla mahina",
)

# Score contribution of each timeline bucket (immediate buyers are hottest).
_TIMELINE_SCORE = {"immediate": 3, "near": 2, "unknown": 1, "long": 0}
_HOT_THRESHOLD = 7
_WARM_THRESHOLD = 5


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_phone(phone: str | None) -> str:
    """Reduce a phone number to a canonical digits-only value for duplicate checks.

    Formatting is stripped, a local trunk prefix ("0") is removed, and when a
    country code is present only the last 10 digits (the national number) are
    kept. This lets "+91 98765 43210", "098765-43210" and "9876543210" resolve
    to the same lead, which is what matters for the Indian market this agent
    targets. A full E.164 parser would be the next step for wider coverage.
    """
    digits = re.sub(r"\D+", "", phone or "").lstrip("0")
    if len(digits) > 10:
        digits = digits[-10:]
    return digits


def classify_timeline(timeline: str | None) -> str:
    """Bucket a free-text purchase timeline into immediate / near / long / unknown."""
    text = (timeline or "").lower()
    if not text:
        return "unknown"
    if any(hint in text for hint in _LONG_TERM_HINTS):
        return "long"
    if any(hint in text for hint in _IMMEDIATE_HINTS):
        return "immediate"
    if any(hint in text for hint in _NEAR_TERM_HINTS):
        return "near"
    return "unknown"


def qualify_interest(lead: LeadInfo) -> InterestLevel:
    """Classify a lead as HOT, WARM or COLD using fixed rules.

    Points are awarded for contactability and completeness, plus the urgency of
    the purchase timeline; the total maps to a fixed band.
    """
    score = 0
    if lead.phone:
        score += 2
    if lead.name:
        score += 1
    if lead.budget:
        score += 1
    if lead.product_interest:
        score += 1
    score += _TIMELINE_SCORE[classify_timeline(lead.purchase_timeline)]

    if score >= _HOT_THRESHOLD:
        return InterestLevel.HOT
    if score >= _WARM_THRESHOLD:
        return InterestLevel.WARM
    return InterestLevel.COLD


def is_qualified(lead: LeadInfo) -> bool:
    """Return True when a conversation has enough to be worth saving as a lead.

    A bare greeting is not saved; a contactable customer (phone plus one more
    detail) or a conversation with at least three details is.
    """
    present = sum(1 for field in LEAD_FIELDS if getattr(lead, field))
    if lead.phone and present >= 2:
        return True
    return present >= 3


def has_lead_signal(lead: LeadInfo) -> bool:
    """Return True when at least one lead detail was captured.

    Used for call-linked leads: a browser/web call without a phone number should
    still become a CRM lead once it has captured a name (or any other detail),
    so the call, its transcript and the customer's name are not lost.
    """
    return any(getattr(lead, field) for field in LEAD_FIELDS)


def _union(existing: list[str] | None, new: list[str]) -> list[str]:
    """Merge two id lists, preserving order and dropping blanks/duplicates."""
    merged = [item for item in (existing or []) if item]
    for item in new:
        if item and item not in merged:
            merged.append(item)
    return merged


def _merge_lead_info(existing: dict[str, Any] | None, incoming: LeadInfo) -> LeadInfo:
    """Combine a new LeadInfo with a stored lead so known values are never lost."""
    existing = existing or {}
    return LeadInfo(
        name=incoming.name or existing.get("name"),
        phone=incoming.phone or existing.get("phone"),
        budget=incoming.budget or existing.get("budget"),
        product_interest=(
            incoming.product_interest
            or existing.get("product_interest")
            or existing.get("requirements")
        ),
        purchase_timeline=incoming.purchase_timeline or existing.get("purchase_timeline"),
    )


class LeadService:
    """Qualifies leads and keeps the CRM in sync with conversations and calls."""

    def __init__(self, store: LeadStore) -> None:
        self._store = store

    def to_lead(self, document: dict[str, Any] | None) -> Lead:
        """Turn a stored document into a Lead model (mapping _id to id)."""
        data = dict(document or {})
        data["id"] = data.pop("_id", data.get("id"))
        # Leads stored before product_interest was persisted only kept the value
        # in `requirements`; surface it under both names for those records.
        if not data.get("product_interest") and data.get("requirements"):
            data["product_interest"] = data["requirements"]
        return Lead(**data)

    def get_lead(self, lead_id: str) -> Lead | None:
        """Return a stored lead by id, or None when it does not exist."""
        document = self._store.get(lead_id)
        return self.to_lead(document) if document else None

    def sync_from_conversation(
        self, conversation: Conversation, *, allow_partial: bool = False
    ) -> Lead | None:
        """Create or update a CRM lead from a conversation's collected lead.

        Returns None when the conversation is not qualified enough to store.
        Existing leads are matched by phone number (to prevent duplicates), then
        by conversation id, so re-syncing the same conversation updates one row.

        With `allow_partial=True` any captured detail (for example just a name
        from a phone-less browser call) is enough to store the lead, instead of
        the stricter `is_qualified` rule used by the text chat endpoint.
        """
        incoming = conversation.lead
        if allow_partial:
            if not has_lead_signal(incoming):
                return None
        elif not is_qualified(incoming):
            return None

        phone_normalized = normalize_phone(incoming.phone)
        existing = None
        if phone_normalized:
            existing = self._store.find_by_phone(phone_normalized)
        if existing is None:
            existing = self._store.find_by_conversation(conversation.id)

        merged = _merge_lead_info(existing, incoming)
        interest = qualify_interest(merged)
        set_fields: dict[str, Any] = {
            "name": merged.name,
            "phone": merged.phone,
            "phone_normalized": normalize_phone(merged.phone),
            "budget": merged.budget,
            "product_interest": merged.product_interest,
            "purchase_timeline": merged.purchase_timeline,
            "requirements": merged.product_interest,
            "interest_level": interest.value,
        }

        if existing is not None:
            updated = self._store.update(
                existing["_id"],
                {
                    **set_fields,
                    "conversation_ids": _union(existing.get("conversation_ids"), [conversation.id]),
                },
            )
            return self.to_lead(updated)

        now = _utcnow()
        document = {
            "_id": str(uuid.uuid4()),
            **set_fields,
            "status": LeadStatus.NEW.value,
            "notes": None,
            "conversation_ids": [conversation.id],
            "call_ids": [],
            "call_history": [],
            "created_at": now,
            "updated_at": now,
        }
        self._store.insert(document)
        return self.to_lead(document)

    def attach_call(self, call: dict[str, Any]) -> Lead | None:
        """Link a finished call to a lead, creating a minimal lead if needed.

        Returns None when the call carries no phone number and no lead exists to
        attach it to. The lead is matched by explicit id first (outbound calls
        pass the CRM lead they were started for), then by phone number, then by
        conversation id, so a call and its conversation share one lead.
        """
        phone_number = call.get("phone_number")
        phone_normalized = normalize_phone(phone_number)
        conversation_id = str(call.get("conversation_id") or "").strip() or None
        call_id = str(call.get("_id") or "").strip()
        if not call_id:
            return None

        explicit_lead_id = str(
            call.get("lead_id") or (call.get("vapi_metadata") or {}).get("lead_id") or ""
        ).strip()

        existing = None
        if explicit_lead_id:
            existing = self._store.get(explicit_lead_id)
        if existing is None and phone_normalized:
            existing = self._store.find_by_phone(phone_normalized)
        if existing is None and conversation_id:
            existing = self._store.find_by_conversation(conversation_id)

        if existing is None:
            if not phone_normalized:
                # Nothing to link the call to.
                return None
            now = _utcnow()
            existing = {
                "_id": str(uuid.uuid4()),
                "name": None,
                "phone": phone_number,
                "phone_normalized": phone_normalized,
                "budget": None,
                "product_interest": None,
                "purchase_timeline": None,
                "requirements": None,
                "interest_level": InterestLevel.COLD.value,
                "status": LeadStatus.NEW.value,
                "notes": None,
                "conversation_ids": [conversation_id] if conversation_id else [],
                "call_ids": [],
                "call_history": [],
                "created_at": now,
                "updated_at": now,
            }
            self._store.insert(existing)

        entry = {
            "call_id": call_id,
            "conversation_id": conversation_id,
            "direction": call.get("direction"),
            "started_at": call.get("started_at"),
            "ended_at": call.get("ended_at"),
            "summary": call.get("summary"),
            "transcript": call.get("transcript"),
        }
        updated = self._store.add_call(existing["_id"], entry, conversation_id=conversation_id)
        return self.to_lead(updated)
