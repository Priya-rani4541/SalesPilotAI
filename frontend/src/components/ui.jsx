// Small, dependency-free UI primitives and formatting helpers shared by every
// dashboard panel.

export function Card({ title, subtitle, actions, children, className = '' }) {
  return (
    <section className={`card ${className}`.trim()}>
      {(title || actions) && (
        <header className="card-head">
          <div>
            {title && <h2 className="card-title">{title}</h2>}
            {subtitle && <p className="card-subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  )
}

export function Badge({ label, tone = 'neutral' }) {
  return <span className={`badge badge-${tone}`}>{label}</span>
}

const LEVEL_TONES = { HOT: 'hot', WARM: 'warm', COLD: 'cold' }
const STATUS_TONES = {
  NEW: 'neutral',
  CONTACTED: 'info',
  QUALIFIED: 'info',
  CONVERTED: 'hot',
  LOST: 'cold',
  SCHEDULED: 'info',
  COMPLETED: 'hot',
  CANCELLED: 'cold',
  POSITIVE: 'hot',
  NEUTRAL: 'warm',
  NEGATIVE: 'cold',
  // Voice call lifecycle statuses (lower-case, from the Vapi webhook).
  queued: 'neutral',
  ringing: 'warm',
  'in-progress': 'info',
  forwarding: 'info',
  ended: 'neutral',
  completed: 'hot',
  failed: 'cold',
}

export function LevelBadge({ level }) {
  if (!level) return <span className="muted">—</span>
  return <Badge label={level} tone={LEVEL_TONES[level] || 'neutral'} />
}

export function StatusBadge({ status, tone }) {
  if (!status) return <span className="muted">—</span>
  return <Badge label={status} tone={tone || STATUS_TONES[status] || 'neutral'} />
}

export function Spinner({ label = 'Loading…' }) {
  return (
    <div className="state state-loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

export function ErrorBanner({ error, onRetry }) {
  if (!error) return null
  const message = typeof error === 'string' ? error : error.message
  const status = typeof error === 'object' && error ? error.status : undefined
  return (
    <div className="state state-error" role="alert">
      <div>
        <strong>Something went wrong.</strong>
        <span className="error-message"> {message}</span>
        {status ? <span className="muted"> (HTTP {status})</span> : null}
      </div>
      {onRetry && (
        <button type="button" className="btn btn-ghost" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  )
}

export function EmptyState({ message }) {
  return <div className="state state-empty">{message}</div>
}

export function ErrorMessage({ error }) {
  if (!error) return null
  const message = typeof error === 'string' ? error : error.message
  return <p className="inline-error" role="alert">{message}</p>
}

// --- Formatting helpers ---

export function formatDateTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

export function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleDateString(undefined, { dateStyle: 'medium' })
}

export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) {
    return '—'
  }
  const total = Math.max(0, Math.round(Number(seconds)))
  const minutes = Math.floor(total / 60)
  const secs = total % 60
  if (minutes === 0) return `${secs}s`
  return `${minutes}m ${secs.toString().padStart(2, '0')}s`
}

export function truncate(text, max = 120) {
  if (!text) return ''
  const value = String(text)
  return value.length > max ? `${value.slice(0, max).trimEnd()}…` : value
}
