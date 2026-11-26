import { api } from '../api/client.js'
import { useAsync } from '../hooks/useAsync.js'
import {
  Card,
  EmptyState,
  ErrorBanner,
  LevelBadge,
  Spinner,
  StatusBadge,
  formatDateTime,
  truncate,
} from './ui.jsx'

function Kpi({ label, value, tone, hint }) {
  return (
    <div className={`kpi ${tone ? `kpi-${tone}` : ''}`.trim()}>
      <span className="kpi-value">{value}</span>
      <span className="kpi-label">{label}</span>
      {hint && <span className="kpi-hint">{hint}</span>}
    </div>
  )
}

function countBy(items, key, value) {
  return items.filter((item) => item && item[key] === value).length
}

export default function OverviewPanel({ onNavigate }) {
  const { data, loading, error, reload } = useAsync(async () => {
    const [leads, calls, appointments, summaries] = await Promise.all([
      api.listLeads({ limit: 200 }),
      api.listCalls({ limit: 200 }),
      api.listAppointments({ limit: 200 }),
      api.listSummaries({ limit: 200 }),
    ])
    return {
      leads: leads.leads || [],
      calls: calls.calls || [],
      appointments: appointments.appointments || [],
      summaries: summaries.summaries || [],
    }
  }, [])

  if (loading) return <Spinner label="Loading dashboard…" />
  if (error) return <ErrorBanner error={error} onRetry={reload} />

  const leads = data.leads
  const hot = countBy(leads, 'interest_level', 'HOT')
  const warm = countBy(leads, 'interest_level', 'WARM')
  const cold = countBy(leads, 'interest_level', 'COLD')
  const upcoming = data.appointments.filter(
    (a) => a.status === 'SCHEDULED' && new Date(a.scheduled_at) >= new Date(),
  )
  const positive = countBy(data.summaries, 'sentiment', 'POSITIVE')

  const recentLeads = [...leads].slice(0, 6)

  return (
    <div className="stack">
      <div className="kpi-grid">
        <Kpi label="Total leads" value={leads.length} hint={`${data.calls.length} calls`} />
        <Kpi label="HOT" value={hot} tone="hot" hint="Ready to buy" />
        <Kpi label="WARM" value={warm} tone="warm" hint="Interested" />
        <Kpi label="COLD" value={cold} tone="cold" hint="Low intent" />
        <Kpi label="Upcoming appointments" value={upcoming.length} hint={`${data.appointments.length} total`} />
        <Kpi label="Summaries" value={data.summaries.length} hint={`${positive} positive`} />
      </div>

      <Card
        title="Recent leads"
        subtitle="Newest qualified leads from voice and chat conversations."
        actions={
          <button type="button" className="btn btn-ghost" onClick={() => onNavigate('leads')}>
            View all
          </button>
        }
      >
        {recentLeads.length === 0 ? (
          <EmptyState message="No leads yet. Start a chat or place a call to create one." />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Phone</th>
                  <th>Interest</th>
                  <th>Status</th>
                  <th>Requirements</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {recentLeads.map((lead) => (
                  <tr key={lead.id}>
                    <td>{lead.name || <span className="muted">Unknown</span>}</td>
                    <td>{lead.phone || <span className="muted">—</span>}</td>
                    <td><LevelBadge level={lead.interest_level} /></td>
                    <td><StatusBadge status={lead.status} /></td>
                    <td>{truncate(lead.requirements, 60) || <span className="muted">—</span>}</td>
                    <td>{formatDateTime(lead.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
