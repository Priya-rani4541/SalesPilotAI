# SalesPilot AI — Audit & Fix Progress

Last updated: 2026-11-26
Scope: audit + fix (Vapi Custom LLM, CRM, dashboard). No rebuild, secrets preserved, no paid services.
Mode: audit of existing code — only targeted fixes applied.

## Stage summary

| # | Stage | Status |
|---|-------|--------|
| 1 | Vapi webhook auth + auto call→CRM lead saving | PASS (2 fixes) |
| 2 | Lead extraction (name/phone/budget/interest/timeline) | PASS (1 fix) |
| 3 | Save calls/transcripts/summaries/sentiment/objections + linking | PASS (verified) |
| 4 | Duplicate lead + webhook event prevention | PASS (verified) |
| 5 | VAPI_ASSISTANT_ID + environment configuration | PASS (manual credential pending) |
| 6 | Verify chat/Mongo/leads/calls/summaries/appointments/RAG | PASS (verified live) |
| 7 | Dashboard bugs + lead details view | PASS |
| 8 | Backend compile check + frontend build | PASS |
| 9 | PROGRESS.md + final report | DONE |
| 10 | Outbound Phone Calling module (Vapi) | PASS (code + webhooks); real call NOT verified — see below |
| 11 | Vapi browser Web Call + AI Chat persistence | PASS (verified via test web call + webhook) — see below |

## Fixes applied (code changes)

1. **`backend/app/services/vapi_service.py` — `_record_end_of_call`**
   Bug: when Vapi sent an end-of-call report with no `metadata.conversation_id`, the call was
   stored with `conversation_id=None`, so the finished call was never linked to its conversation
   or CRM lead.
   Fix: fall back to the call id (the Custom LLM turn already uses the call id as the
   conversation id), so the call stays linked to its conversation → lead.

2. **`backend/app/services/lead_service.py` — `_merge_lead_info`**
   Bug: an existing `purchase_timeline` was dropped whenever a later turn omitted it
   (`incoming.purchase_timeline` had no fallback), causing data loss mid-conversation.
   Also hardened the `product_interest` fallback (`product_interest` → `requirements`).
   Fix: preserve the existing value when the incoming turn doesn't supply one.

3. **`backend/app/api/routes/vapi.py` — `POST /api/vapi/call`**
   Bug: the outbound-call endpoint had no secret check while the webhook/LLM endpoints did.
   Fix: added `_check_secret(request)`. Verified: no secret → HTTP 401.

4. **`backend/.env` — `PUBLIC_BASE_URL`**
   Updated to the current Cloudflare Quick Tunnel URL (old tunnel had expired → HTTP 530).
   Note: quick tunnels get a new URL on every restart; update Vapi dashboard too.

## Tests run (all against the live backend + MongoDB Atlas)

- Static: `python -m compileall -q app` → exit 0 (no syntax errors). No project test suite exists.
- Build: `npm run build` (frontend) → 37 modules, `dist/assets/index-CE6wvlgu.js` 178.65 kB. PASS.
- Health: `GET /api/health` → `{"status":"ok"}`. PASS.
- Webhook auth: no secret → 401; with secret → `{"received":true}`; repeat → `{"duplicate":true}`. PASS.
- End-to-end call→CRM (no Gemini): posted `end-of-call-report` (no metadata, no transcript) with
  Rahul's phone → call stored with `conversation_id` = call id (fix #1), appended to Rahul's
  `call_history`, deduped to exactly 1 lead. PASS.
- Lists: leads=6, calls=13, summaries=2, appointments=2, documents=1. PASS.
- AI Chat: `POST /api/agent/chat` → real Gemini reply, conversation persisted, lead extraction
  running, `missing_fields` correct. PASS.
- RAG: `POST /api/knowledge/query` "What is the refund policy?" → `found=true`, grounded answer,
  top score 0.663 (≥ 0.50 threshold), model `gemini-2.5-flash-lite`. Out-of-scope query →
  `found=false` fallback (no generation). PASS.
- Summaries: linked `call_id` + `conversation_id` + `lead_id`, with sentiment + objections. PASS.

## Files changed
- `backend/app/services/vapi_service.py` — conversation_id fallback on end-of-call report.
- `backend/app/services/lead_service.py` — preserve purchase_timeline + product_interest merge.
- `backend/app/api/routes/vapi.py` — secret check on outbound `/call` endpoint.
- `backend/.env` — `PUBLIC_BASE_URL` updated to active tunnel.
- `PROGRESS.md` — this file.

## Outbound Phone Calling module (this task)

### Requirement status

| # | Requirement | Result |
|---|-------------|--------|
| 1 | Vapi env config: `VAPI_API_KEY`, `VAPI_PHONE_NUMBER_ID`, `VAPI_ASSISTANT_ID` | PASS (wired + validated; values still empty — see manual setup) |
| 2 | Secure outbound call API taking phone + lead details | PASS |
| 3 | Initiate call through Vapi (assistant + phone number) | IMPLEMENTED — NOT VERIFIED against a real call (credentials empty) |
| 4 | Status webhooks: `queued`, `ringing`, `in-progress`, `completed`, `failed` | PASS |
| 5 | Save call id, status, timestamps, duration, transcript, summary in MongoDB | PASS |
| 6 | Link outbound call to the correct CRM lead | PASS |
| 7 | Validation, error handling, duplicate-event protection | PASS |
| 8 | Frontend outbound-call action in the Lead details view | PASS (added) |
| 9 | Tests + frontend build | PASS |

### Code changes

1. **`backend/app/schemas/vapi.py` — `OutboundCallRequest`**
   Rewrote the request model to accept `phone_number` plus optional lead context
   (`lead_id`, `conversation_id`, `assistant_id`, `customer_name`). Added validators:
   a number with fewer than 8 digits is rejected (422), blank optional strings become
   "not provided", and `extra="forbid"` rejects unknown fields.

2. **`backend/app/services/vapi_service.py` — outbound flow**
   - `start_outbound_call(...)` extended: validates the dialable number, verifies a
     supplied `lead_id` exists (typo → 422, no stray lead), requires `VAPI_API_KEY` /
     `VAPI_PHONE_NUMBER_ID` / an assistant id (each missing → clear 503), builds the Vapi
     `POST /call` body with `metadata.conversation_id` + `metadata.lead_id`, records the
     call (`direction=outbound`, status, lead id) and links it to the CRM immediately.
   - New `_status_from_end()` maps the end-of-call report to `completed` / `failed`
     (no-answer, busy, declined, error, unreachable, … → `failed`).
   - New `_link_call_to_crm()` attaches the freshly created outbound call to its lead
     (best effort; failures logged and swallowed).
   - `_attach_lead()` now prefers the stored call document (holds the resolved
     conversation id / explicit lead id) so end-of-call linking is reliable.

3. **`backend/app/services/lead_service.py`**
   Added `get_lead()` (used to validate the supplied lead); `attach_call()` now matches
   by explicit `lead_id` first, then phone, then conversation.

4. **`backend/app/api/routes/vapi.py` — `POST /api/vapi/call`**
   Passes `lead_id` and `customer_name` through; already guarded by `_check_secret`.

5. **Frontend**
   - `frontend/src/api/client.js`: added `api.startCall(payload)` → `POST /api/vapi/call`.
   - `frontend/src/components/LeadsPanel.jsx`: added an "Outbound call" action (Start call
     button) in the Lead details modal with loading/error/success states.
   - `frontend/src/components/ui.jsx`: added call lifecycle tones (`queued`, `ringing`,
     `in-progress`, `forwarding`, `ended`, `completed`, `failed`) to `STATUS_TONES`.

### Tests run (live backend + MongoDB Atlas; no paid services)

- `python -m compileall -q app` → exit 0. No project test suite exists.
- `npm run build` → 37 modules, `dist/assets/index-2YKVsr0Q.js` 179.88 kB. PASS.
- Outbound validation matrix: no secret → 401; <8 digits → 422; unknown `lead_id` → 422;
  unknown field → 422; valid number + real lead → 503 (`VAPI_API_KEY is not configured`). PASS.
- Lifecycle webhook: `queued` / `ringing` / `in-progress` → `{"received":true}`; repeated
  `in-progress` → `{"received":true,"duplicate":true}` (idempotent); after status events the
  call shows `status=in-progress direction=outbound`. PASS.
- End-of-call report → call `status=completed`, `ended_reason=customer-ended-call`,
  `duration_seconds=42`, transcript + summary stored, `conversation_id` = call id; repeated
  report → `duplicate:true`. PASS.
- CRM linking → the outbound test call appears in the lead (`Rahul`) `call_ids` and
  `call_history` with its summary. PASS.

## Remaining issues / manual steps
- `VAPI_API_KEY`, `VAPI_PHONE_NUMBER_ID`, `VAPI_ASSISTANT_ID` are **empty** in `backend/.env`.
  The outbound `/api/vapi/call` endpoint therefore returns a clear 503 (never a fake success).
  Fill these from the Vapi dashboard to enable outbound calling.
- Cloudflare Quick Tunnel is ephemeral: on each restart update `PUBLIC_BASE_URL` and the Vapi
  assistant's Custom LLM Server URL + Server Secret.
- Pre-existing demo rows (some calls/leads/summaries/appointments created by earlier tests) were
  left in place (not deleted).

## Next steps / commands
```
# Backend (already running on port 8000)
cd backend
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --port 8000

# Tunnel for Vapi
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8000

# Frontend
cd frontend
npm run build
npm run dev
```

## Vapi browser Web Call + AI Chat persistence (this task)

Goal: find out why a Vapi **browser Web Call** with customer "Priya Rani" showed up in Vapi but
not in CRM Leads / Calls / Summaries, then fix the persistence path for both web calls and AI
chat — without touching existing data or the modules that already worked.

### Diagnosis (evidence from a read-only MongoDB dump)

- A stored call `01a216be-…` existed with `direction=web`, `call_type=webCall`, `status=null`,
  `phone_number=null`, and **no `webhook_events` entry** — i.e. no server message
  (`end-of-call-report`) ever reached the backend for that call.
- `leads` search for "priya"/"rani" → **0 rows**: a name-only lead was dropped because
  `sync_from_conversation` required a *fully* qualified lead (strict `is_qualified`, phone required).
- No summary existed for those web calls.

### Root causes

1. `VapiService.run_turn` (Custom LLM turn) only saved the conversation — it never synced the
   CRM lead, never stored the running transcript and never linked the call to a lead. So a
   browser call only appeared in CRM **after** an end-of-call webhook arrived.
2. The reported call never received a server message at all → nothing was ever written to
   `calls` history beyond the initial row, and no lead/summary was created.
3. `sync_from_conversation` / `attach_call` could not handle a **phone-less** web call (no number
   to dedupe on) so even a captured name was discarded.
4. AI-chat conversations that only captured a name (no phone) were dropped by the strict
   qualification check, so they never reached Leads.
5. Transcript extraction only read `message.transcript` / `artifact.transcript`; browser calls
   that send only structured `artifact.messages` produced no transcript → no summary.

### Fixes applied

1. **`backend/app/services/sales_agent.py`** — added `TRANSCRIPT_EXTRACTION_PROMPT` and
   `extract_lead_from_transcript(transcript) -> LeadInfo | None`, a best-effort Gemini extraction
   used as a fallback when a call bypassed the Custom LLM (so the lead still comes from the real
   transcript, never invented). Returns `None` on any failure.

2. **`backend/app/services/lead_service.py`** — added `has_lead_signal(lead)` and an
   `allow_partial` kwarg on `sync_from_conversation`: with `allow_partial=True` a lead is stored
   as soon as **any** detail (e.g. just a name) is captured, so phone-less web calls and name-only
   chats still land in Leads. Dedup still runs by phone when present.

3. **`backend/app/services/vapi_service.py`**
   - `run_turn` now persists on every Custom LLM turn: `_sync_lead_from_conversation`,
     `_store_transcript`, `_link_call_to_crm` (all best-effort, logged + swallowed).
   - New `_extract_transcript(message, artifact)` flattens structured `artifact.messages` /
     `message.messages` into `"Customer: …" / "Agent: …"` lines when no plain transcript string
     is present.
   - `_attach_lead` now: prefers the stored call document, falls back to extracting the lead from
     the call transcript when the conversation captured nothing, and syncs with
     `allow_partial=True` so a phone-less browser call is stored.

4. **`backend/app/api/routes/agent.py`** — the chat route now calls
   `sync_from_conversation(conversation, allow_partial=True)` so a name-only AI chat is kept.

### Tests performed (live backend on port 8000 + MongoDB Atlas, real Gemini)

- `python -m compileall -q app` → exit 0; `python -c "import app.main"` → `import OK`.
- `GET /api/health` → `{"status":"ok"}`.
- **Custom LLM web-call turn** (no phone, no webhook): `POST /api/vapi/llm/chat/completions`
  with `type=webCall` → HTTP 200 reply; call stored `direction=web`, `conversation_id` set,
  transcript stored; lead created (`name=Testy Webcall`, `call_ids=[…]`). **PASS**
- **Structured-only transcript**: `end-of-call-report` carrying only `artifact.messages` →
  call `status=completed`, transcript flattened to
  `"Agent: Hello, how can I help?\nCustomer: I am Priya Rani, budget 70000 per month."` **PASS**
- **End-of-call report for the web call** → `status=completed`, `duration=95`, summary stored and
  linked to both call and lead; `summaries` count increased. **PASS**
- **Idempotency**: repeating any webhook → `{"duplicate":true}`; no second lead created. **PASS**
- Full run stayed green and the backend reported `MongoDB configured: True`, Gemini key set,
  model `gemini-2.5-flash-lite`.

### Files changed (this task)
- `backend/app/services/sales_agent.py` — `TRANSCRIPT_EXTRACTION_PROMPT`, `extract_lead_from_transcript`.
- `backend/app/services/lead_service.py` — `has_lead_signal`, `allow_partial` in `sync_from_conversation`.
- `backend/app/services/vapi_service.py` — `_extract_transcript`, per-turn CRM/transcript linking,
  transcript-fallback lead extraction, partial-lead sync.
- `backend/app/api/routes/agent.py` — partial-lead sync on chat.
- `PROGRESS.md` — this section.

### Remaining issues

- The **original** browser call `01a216be-…` ("Priya Rani") is a historical record that never
  received a server message; it was **left in place** (not deleted/modified) per the "preserve
  existing data" instruction. It will not retroactively gain a lead/summary unless its transcript
  is replayed through the webhook; the fix applies going forward.
- Test rows created during verification (web call `webtest-…`, lead "Testy Webcall") remain in
  MongoDB and can be removed manually if a clean CRM is wanted.
- For a real browser call to reach the CRM **during** the call, the Vapi assistant must point its
  Custom LLM Server URL at the current Cloudflare tunnel (`PUBLIC_BASE_URL`) — the tunnel URL is
  ephemeral and must be updated on each restart.

