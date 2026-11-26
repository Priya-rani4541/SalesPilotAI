import { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../hooks/useAsync.js'
import {
  Card,
  EmptyState,
  ErrorBanner,
  ErrorMessage,
  LevelBadge,
  Spinner,
  StatusBadge,
  formatDateTime,
  truncate,
} from './ui.jsx'

const LEVELS = ['ALL', 'HOT', 'WARM', 'COLD']
const STATUSES = ['ALL', 'NEW', 'CONTACTED', 'QUALIFIED', 'CONVERTED', 'LOST']

export default function LeadsPanel() {
  const [level, setLevel] = useState('ALL')
  const [status, setStatus] = useState('ALL')
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState(null)

  const { data, loading, error, reload } = useAsync(
    () =>
      api.listLeads({
        limit: 200,
        interest_level: level === 'ALL' ? undefined : level,
        status: status === 'ALL' ? undefined : status,
        q: search.trim() || undefined,
      }),
    [level, status, search],
  )

  const leads = data?.leads || []

  return (
    <div className="stack">
      <Card
        title="Leads"
        subtitle={data ? `${data.total} lead(s) match the current filters.` : 'Qualified leads from every channel.'}
      >
        <div className="filters">
          <label className="field">
            <span>Interest</span>
            <select value={level} onChange={(e) => setLevel(e.target.value)}>
              {LEVELS.map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Status</span>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
          <label className="field field-grow">
            <span>Search</span>
            <input
              type="search"
              placeholder="Name, phone, requirement or budget"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <button type="button" className="btn btn-ghost" onClick={reload}>Refresh</button>
        </div>

        {loading && <Spinner label="Loading leads…" />}
        {error && <ErrorBanner error={error} onRetry={reload} />}
        {!loading && !error && leads.length === 0 && (
          <EmptyState message="No leads match these filters." />
        )}
        {!loading && !error && leads.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Phone</th>
                  <th>Interest</th>
                  <th>Status</th>
                  <th>Budget</th>
                  <th>Requirements</th>
                  <th>Updated</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {leads.map((lead) => (
                  <tr
                    key={lead.id}
                    className="clickable"
                    onClick={() => setSelectedId(lead.id)}
                    title="View details"
                  >
                    <td>{lead.name || <span className="muted">Unknown</span>}</td>
                    <td>{lead.phone || <span className="muted">—</span>}</td>
                    <td><LevelBadge level={lead.interest_level} /></td>
                    <td><StatusBadge status={lead.status} /></td>
                    <td>{lead.budget || <span className="muted">—</span>}</td>
                    <td>{truncate(lead.requirements, 60) || <span className="muted">—</span>}</td>
                    <td>{formatDateTime(lead.updated_at || lead.created_at)}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-mini"
                        onClick={(e) => {
                          e.stopPropagation()
                          setSelectedId(lead.id)
                        }}
                      >
                        View details
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {selectedId && (
        <LeadDetail
          leadId={selectedId}
          onClose={() => setSelectedId(null)}
          onSaved={reload}
        />
      )}
    </div>
  )
}

function LeadDetail({ leadId, onClose, onSaved }) {
  // Full details are fetched from the API (not reused from the list row).
  const { data: lead, loading, error, reload } = useAsync(() => api.getLead(leadId), [leadId])

  const [status, setStatus] = useState('')
  const [interest, setInterest] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [calling, setCalling] = useState(false)
  const [callError, setCallError] = useState(null)
  const [callResult, setCallResult] = useState(null)

  useEffect(() => {
    if (lead) {
      setStatus(lead.status || 'NEW')
      setInterest(lead.interest_level || 'COLD')
      setNotes(lead.notes || '')
    }
  }, [lead])

  async function save() {
    setSaving(true)
    setSaveError(null)
    try {
      await api.updateLead(leadId, {
        status,
        interest_level: interest,
        notes: notes.trim() || null,
      })
      reload()
      onSaved?.()
    } catch (err) {
      setSaveError(err)
    } finally {
      setSaving(false)
    }
  }

  async function startCall() {
    if (!lead?.phone) {
      setCallError('This lead has no phone number to call.')
      return
    }
    setCalling(true)
    setCallError(null)
    setCallResult(null)
    try {
      const result = await api.startCall({
        phone_number: lead.phone,
        lead_id: lead.id,
        customer_name: lead.name || null,
      })
      setCallResult(result)
      // Refresh so the new call appears in the lead's call history.
      reload()
      onSaved?.()
    } catch (err) {
      setCallError(err)
    } finally {
      setCalling(false)
    }
  }

  const history = lead?.call_history || []

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <header className="modal-head">
          <h2>{lead?.name || 'Lead details'}</h2>
          <button type="button" className="btn btn-ghost" onClick={onClose}>Close</button>
        </header>

        <div className="modal-body">
          {loading && <Spinner label="Loading lead details…" />}
          {error && <ErrorBanner error={error} onRetry={reload} />}

          {!loading && !error && lead && (
            <>
              <dl className="detail-list">
                <div><dt>Name</dt><dd>{lead.name || '—'}</dd></div>
                <div><dt>Phone</dt><dd>{lead.phone || '—'}</dd></div>
                <div><dt>Budget</dt><dd>{lead.budget || '—'}</dd></div>
                <div><dt>Product interest</dt><dd>{lead.product_interest || '—'}</dd></div>
                <div><dt>Purchase timeline</dt><dd>{lead.purchase_timeline || '—'}</dd></div>
                <div><dt>Requirements</dt><dd>{lead.requirements || '—'}</dd></div>
                <div><dt>Interest level</dt><dd><LevelBadge level={lead.interest_level} /></dd></div>
                <div><dt>Status</dt><dd><StatusBadge status={lead.status} /></dd></div>
                <div><dt>Created</dt><dd>{formatDateTime(lead.created_at)}</dd></div>
                <div><dt>Updated</dt><dd>{formatDateTime(lead.updated_at)}</dd></div>
                <div><dt>Conversations</dt><dd>{(lead.conversation_ids || []).length}</dd></div>
                <div><dt>Calls</dt><dd>{history.length || (lead.call_ids || []).length}</dd></div>
              </dl>

              <div className="form-grid">
                <label className="field">
                  <span>Interest level</span>
                  <select value={interest} onChange={(e) => setInterest(e.target.value)}>
                    {['HOT', 'WARM', 'COLD'].map((value) => (
                      <option key={value} value={value}>{value}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Status</span>
                  <select value={status} onChange={(e) => setStatus(e.target.value)}>
                    {STATUSES.slice(1).map((value) => (
                      <option key={value} value={value}>{value}</option>
                    ))}
                  </select>
                </label>
                <label className="field field-full">
                  <span>Notes</span>
                  <textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
                </label>
              </div>

              <ErrorMessage error={saveError} />

              <div className="modal-actions">
                <button type="button" className="btn btn-primary" onClick={save} disabled={saving}>
                  {saving ? 'Saving…' : 'Save changes'}
                </button>
              </div>

              <div className="block">
                <h3>Outbound call</h3>
                <p className="muted">
                  Place an AI voice call to this lead through the Vapi assistant.
                </p>
                <div className="modal-actions">
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={startCall}
                    disabled={calling || !lead.phone}
                  >
                    {calling ? 'Starting call…' : 'Start call'}
                  </button>
                </div>
                {!lead.phone && <p className="muted">No phone number on this lead.</p>}
                <ErrorMessage error={callError} />
                {callResult && (
                  <p className="inline-success">
                    Call {callResult.status || 'queued'}
                    {callResult.call_id ? (
                      <>
                        {' '}— id <span className="mono">{callResult.call_id}</span>
                      </>
                    ) : null}
                  </p>
                )}
              </div>

              <div className="block">
                <h3>Call history</h3>
                {history.length === 0 ? (
                  <p className="muted">No calls recorded for this lead yet.</p>
                ) : (
                  <ul className="history-list">
                    {history.map((call) => (
                      <li key={call.call_id} className="history-item">
                        <div className="history-head">
                          <StatusBadge status={(call.direction || 'CALL').toUpperCase()} tone="info" />
                          <span className="muted">{formatDateTime(call.started_at)}</span>
                          {call.ended_at && (
                            <span className="muted">→ {formatDateTime(call.ended_at)}</span>
                          )}
                        </div>
                        {call.summary && <p className="history-summary">{call.summary}</p>}
                        {call.transcript && (
                          <details className="sources">
                            <summary>View transcript</summary>
                            <pre className="transcript">{call.transcript}</pre>
                          </details>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
