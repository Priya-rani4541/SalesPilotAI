import { useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../hooks/useAsync.js'
import {
  Card,
  EmptyState,
  ErrorBanner,
  Spinner,
  StatusBadge,
  formatDateTime,
  formatDuration,
  truncate,
} from './ui.jsx'

export default function CallsPanel() {
  const [selected, setSelected] = useState(null)
  const { data, loading, error, reload } = useAsync(
    () => api.listCalls({ limit: 200 }),
    [],
  )
  const calls = data?.calls || []

  return (
    <div className="stack">
      <Card
        title="Call history"
        subtitle={data ? `${data.total} call(s) recorded by the Vapi webhook.` : 'Voice calls stored by the Vapi webhook.'}
        actions={<button type="button" className="btn btn-ghost" onClick={reload}>Refresh</button>}
      >
        {loading && <Spinner label="Loading calls…" />}
        {error && <ErrorBanner error={error} onRetry={reload} />}
        {!loading && !error && calls.length === 0 && (
          <EmptyState message="No calls yet. Calls appear once the Vapi webhook receives an end-of-call report." />
        )}
        {!loading && !error && calls.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Phone</th>
                  <th>Direction</th>
                  <th>Status</th>
                  <th>Duration</th>
                  <th>Summary</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((call) => (
                  <tr key={call.id} className="clickable" onClick={() => setSelected(call)}>
                    <td>{call.phone_number || <span className="muted">—</span>}</td>
                    <td>{call.direction || <span className="muted">—</span>}</td>
                    <td><StatusBadge status={call.status} /></td>
                    <td>{formatDuration(call.duration_seconds)}</td>
                    <td>{truncate(call.summary, 60) || <span className="muted">—</span>}</td>
                    <td>{formatDateTime(call.started_at || call.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {selected && <CallDetail call={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

function CallDetail({ call, onClose }) {
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head">
          <h2>Call {call.phone_number || call.id}</h2>
          <button type="button" className="btn btn-ghost" onClick={onClose}>Close</button>
        </header>

        <dl className="detail-list">
          <div><dt>Status</dt><dd><StatusBadge status={call.status} /></dd></div>
          <div><dt>Direction</dt><dd>{call.direction || '—'}</dd></div>
          <div><dt>Ended reason</dt><dd>{call.ended_reason || '—'}</dd></div>
          <div><dt>Duration</dt><dd>{formatDuration(call.duration_seconds)}</dd></div>
          <div><dt>Started</dt><dd>{formatDateTime(call.started_at)}</dd></div>
          <div><dt>Ended</dt><dd>{formatDateTime(call.ended_at)}</dd></div>
          <div><dt>Conversation</dt><dd className="mono">{call.conversation_id || '—'}</dd></div>
        </dl>

        {call.summary && (
          <div className="block">
            <h3>Summary</h3>
            <p>{call.summary}</p>
          </div>
        )}

        <div className="block">
          <h3>Transcript</h3>
          <pre className="transcript">{call.transcript || 'No transcript stored for this call.'}</pre>
        </div>

        {call.recording_url && (
          <div className="block">
            <h3>Recording</h3>
            <a className="link" href={call.recording_url} target="_blank" rel="noreferrer">
              Open recording
            </a>
          </div>
        )}
      </aside>
    </div>
  )
}
