import { useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../hooks/useAsync.js'
import {
  Card,
  EmptyState,
  ErrorBanner,
  ErrorMessage,
  Spinner,
  StatusBadge,
  formatDateTime,
  truncate,
} from './ui.jsx'

function BulletList({ items }) {
  if (!items || items.length === 0) return <span className="muted">None noted.</span>
  return (
    <ul className="bullets">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  )
}

export default function SummariesPanel() {
  const [selected, setSelected] = useState(null)
  const [sentiment, setSentiment] = useState('ALL')
  const { data, loading, error, reload } = useAsync(
    () => api.listSummaries({ limit: 200, sentiment: sentiment === 'ALL' ? undefined : sentiment }),
    [sentiment],
  )
  const summaries = data?.summaries || []

  return (
    <div className="stack">
      <Card
        title="Call summaries"
        subtitle={data ? `${data.total} summary(ies) generated from call transcripts.` : 'AI summaries, requirements, objections and sentiment.'}
        actions={
          <>
            <label className="field inline">
              <span>Sentiment</span>
              <select value={sentiment} onChange={(e) => setSentiment(e.target.value)}>
                {['ALL', 'POSITIVE', 'NEUTRAL', 'NEGATIVE'].map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </label>
            <button type="button" className="btn btn-ghost" onClick={reload}>Refresh</button>
          </>
        }
      >
        {loading && <Spinner label="Loading summaries…" />}
        {error && <ErrorBanner error={error} onRetry={reload} />}
        {!loading && !error && summaries.length === 0 && (
          <EmptyState message="No summaries yet. Generate one below or via the Vapi webhook." />
        )}
        {!loading && !error && summaries.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Summary</th>
                  <th>Sentiment</th>
                  <th>Lead</th>
                  <th>Call</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {summaries.map((item) => (
                  <tr key={item.id} className="clickable" onClick={() => setSelected(item)}>
                    <td>{truncate(item.summary, 80)}</td>
                    <td><StatusBadge status={item.sentiment} /></td>
                    <td className="mono">{item.lead_id ? truncate(item.lead_id, 10) : '—'}</td>
                    <td className="mono">{item.call_id ? truncate(item.call_id, 10) : '—'}</td>
                    <td>{formatDateTime(item.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <GenerateSummaryForm onGenerated={reload} />

      {selected && <SummaryDetail summary={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

function GenerateSummaryForm({ onGenerated }) {
  const [transcript, setTranscript] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  async function generate() {
    if (!transcript.trim()) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const summary = await api.generateSummary({ transcript: transcript.trim() })
      setResult(summary)
      setTranscript('')
      onGenerated()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card
      title="Generate a summary"
      subtitle="Paste a transcript to have Gemini extract the summary, requirements, objections, sentiment and follow-ups."
    >
      <label className="field field-full">
        <span>Transcript</span>
        <textarea
          rows={5}
          placeholder={'Customer: I am looking for a CRM for my team of 12...\nAgent: Great, what is your budget?'}
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
        />
      </label>
      <ErrorMessage error={error} />
      <div className="drawer-actions">
        <button type="button" className="btn btn-primary" onClick={generate} disabled={busy || !transcript.trim()}>
          {busy ? 'Generating…' : 'Generate summary'}
        </button>
      </div>
      {result && (
        <div className="block callout">
          <h3>Result</h3>
          <p>{result.summary}</p>
          <p><StatusBadge status={result.sentiment} /></p>
        </div>
      )}
    </Card>
  )
}

function SummaryDetail({ summary, onClose }) {
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head">
          <h2>Call summary</h2>
          <button type="button" className="btn btn-ghost" onClick={onClose}>Close</button>
        </header>

        <p className="lead-text">{summary.summary}</p>

        <dl className="detail-list">
          <div><dt>Sentiment</dt><dd><StatusBadge status={summary.sentiment} /></dd></div>
          <div><dt>Model</dt><dd>{summary.model || '—'}</dd></div>
          <div><dt>Created</dt><dd>{formatDateTime(summary.created_at)}</dd></div>
        </dl>

        <div className="block">
          <h3>Requirements</h3>
          <BulletList items={summary.requirements} />
        </div>
        <div className="block">
          <h3>Objections</h3>
          <BulletList items={summary.objections} />
        </div>
        <div className="block">
          <h3>Recommended follow-ups</h3>
          <BulletList items={summary.follow_up_actions} />
        </div>
      </aside>
    </div>
  )
}
