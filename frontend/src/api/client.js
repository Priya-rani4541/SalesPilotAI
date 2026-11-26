// Thin fetch wrapper around the SalesPilot AI backend.
//
// Every call goes through `request`, so error handling, the backend base URL
// and JSON parsing live in exactly one place. Failures are surfaced as an
// ApiError carrying the HTTP status and a human-readable message taken from
// FastAPI's `detail` field.

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
).replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// FastAPI returns `detail` as a string for handled errors, or as a list of
// {loc, msg, type} objects for request-validation (422) failures.
function formatDetail(detail, status) {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => (item && typeof item.msg === 'string' ? item.msg : null))
      .filter(Boolean)
    if (parts.length) return parts.join('; ')
  }
  if (detail && typeof detail === 'object' && typeof detail.msg === 'string') {
    return detail.msg
  }
  return `Request failed (HTTP ${status})`
}

export async function request(path, options = {}) {
  const url = `${API_BASE_URL}${path}`
  let response
  try {
    response = await fetch(url, options)
  } catch (err) {
    throw new ApiError(
      `Cannot reach the backend at ${API_BASE_URL}. Make sure it is running.`,
      0,
    )
  }

  const text = await response.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }

  if (!response.ok) {
    const detail = data && typeof data === 'object' ? data.detail : data
    throw new ApiError(formatDetail(detail, response.status), response.status)
  }
  return data
}

const jsonHeaders = { 'Content-Type': 'application/json' }

export const api = {
  baseUrl: API_BASE_URL,

  health: () => request('/api/health'),

  // --- Sales agent chat ---
  chat: (message, conversationId) =>
    request('/api/agent/chat', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ message, conversation_id: conversationId || null }),
    }),

  // --- CRM leads ---
  listLeads: (params = {}) => request(`/api/leads${toQuery(params)}`),
  getLead: (id) => request(`/api/leads/${encodeURIComponent(id)}`),
  updateLead: (id, changes) =>
    request(`/api/leads/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: jsonHeaders,
      body: JSON.stringify(changes),
    }),

  // --- Call history ---
  listCalls: (params = {}) => request(`/api/calls${toQuery(params)}`),
  getCall: (id) => request(`/api/calls/${encodeURIComponent(id)}`),

  // --- Outbound calling (Vapi) ---
  startCall: (payload) =>
    request('/api/vapi/call', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),

  // --- Call summaries ---
  listSummaries: (params = {}) => request(`/api/summaries${toQuery(params)}`),
  generateSummary: (source) =>
    request('/api/summaries/generate', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(source),
    }),

  // --- Appointments ---
  listAppointments: (params = {}) => request(`/api/appointments${toQuery(params)}`),
  createAppointment: (payload) =>
    request('/api/appointments', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  updateAppointment: (id, changes) =>
    request(`/api/appointments/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: jsonHeaders,
      body: JSON.stringify(changes),
    }),

  // --- RAG knowledge base ---
  listDocuments: () => request('/api/knowledge/documents'),
  uploadDocument: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/api/knowledge/documents', { method: 'POST', body: form })
  },
  queryKnowledge: (question) =>
    request('/api/knowledge/query', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ question }),
    }),
}

function toQuery(params) {
  const entries = Object.entries(params).filter(
    ([, value]) => value !== undefined && value !== null && value !== '',
  )
  if (!entries.length) return ''
  const search = new URLSearchParams()
  entries.forEach(([key, value]) => search.append(key, String(value)))
  return `?${search.toString()}`
}
