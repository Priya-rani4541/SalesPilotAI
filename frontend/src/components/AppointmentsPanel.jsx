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
} from './ui.jsx'

export default function AppointmentsPanel() {
  const [upcoming, setUpcoming] = useState(false)
  const [actionError, setActionError] = useState(null)

  const appointments = useAsync(
    () => api.listAppointments({ limit: 200, upcoming: upcoming ? true : undefined }),
    [upcoming],
  )
  const leads = useAsync(() => api.listLeads({ limit: 200 }), [])

  const items = appointments.data?.appointments || []

  async function changeStatus(id, status) {
    setActionError(null)
    try {
      await api.updateAppointment(id, { status })
      appointments.reload()
    } catch (err) {
      setActionError(err)
    }
  }

  return (
    <div className="stack">
      <Card
        title="Appointments"
        subtitle={appointments.data ? `${appointments.data.total} appointment(s).` : 'Booked consultations linked to leads.'}
        actions={
          <>
            <label className="checkbox">
              <input type="checkbox" checked={upcoming} onChange={(e) => setUpcoming(e.target.checked)} />
              <span>Upcoming only</span>
            </label>
            <button type="button" className="btn btn-ghost" onClick={appointments.reload}>Refresh</button>
          </>
        }
      >
        <ErrorBanner error={actionError} />
        {appointments.loading && <Spinner label="Loading appointments…" />}
        {appointments.error && <ErrorBanner error={appointments.error} onRetry={appointments.reload} />}
        {!appointments.loading && !appointments.error && items.length === 0 && (
          <EmptyState message="No appointments yet. Book one below." />
        )}
        {!appointments.loading && !appointments.error && items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Customer</th>
                  <th>Title</th>
                  <th>Duration</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((appointment) => (
                  <tr key={appointment.id}>
                    <td>{formatDateTime(appointment.scheduled_at)}</td>
                    <td>{appointment.customer_name || appointment.phone || appointment.lead_id || '—'}</td>
                    <td>{appointment.title}</td>
                    <td>{appointment.duration_minutes} min</td>
                    <td><StatusBadge status={appointment.status} /></td>
                    <td>
                      <div className="row-actions">
                        {appointment.status !== 'COMPLETED' && (
                          <button type="button" className="btn btn-mini" onClick={() => changeStatus(appointment.id, 'COMPLETED')}>
                            Complete
                          </button>
                        )}
                        {appointment.status !== 'CANCELLED' && (
                          <button type="button" className="btn btn-mini btn-mini-danger" onClick={() => changeStatus(appointment.id, 'CANCELLED')}>
                            Cancel
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <BookAppointmentForm
        leads={leads.data?.leads || []}
        onBooked={appointments.reload}
      />
    </div>
  )
}

function toLocalInputValue(date) {
  const pad = (n) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

function BookAppointmentForm({ leads, onBooked }) {
  const defaultTime = new Date(Date.now() + 24 * 60 * 60 * 1000)
  const [scheduledAt, setScheduledAt] = useState(toLocalInputValue(defaultTime))
  const [title, setTitle] = useState('Sales consultation')
  const [duration, setDuration] = useState(30)
  const [leadId, setLeadId] = useState('')
  const [phone, setPhone] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  async function book() {
    setError(null)
    setSuccess(null)
    setBusy(true)
    try {
      const payload = {
        scheduled_at: new Date(scheduledAt).toISOString(),
        title: title.trim() || 'Sales consultation',
        duration_minutes: Number(duration),
        lead_id: leadId || undefined,
        phone: phone.trim() || undefined,
        notes: notes.trim() || undefined,
      }
      const created = await api.createAppointment(payload)
      setSuccess(`Booked for ${formatDateTime(created.scheduled_at)}.`)
      setNotes('')
      onBooked()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card
      title="Book an appointment"
      subtitle="An appointment must link to a lead or carry a phone number. Duplicate slots for the same customer are rejected."
    >
      <div className="form-grid">
        <label className="field">
          <span>Date &amp; time</span>
          <input type="datetime-local" value={scheduledAt} onChange={(e) => setScheduledAt(e.target.value)} />
        </label>
        <label className="field">
          <span>Duration (minutes)</span>
          <input
            type="number"
            min={5}
            max={480}
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
          />
        </label>
        <label className="field field-full">
          <span>Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="field">
          <span>Link a lead</span>
          <select value={leadId} onChange={(e) => setLeadId(e.target.value)}>
            <option value="">— Select a lead —</option>
            {leads.map((lead) => (
              <option key={lead.id} value={lead.id}>
                {lead.name || 'Unknown'} {lead.phone ? `(${lead.phone})` : ''}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>…or phone number</span>
          <input placeholder="+91 98765 43210" value={phone} onChange={(e) => setPhone(e.target.value)} />
        </label>
        <label className="field field-full">
          <span>Notes</span>
          <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
      </div>

      <ErrorMessage error={error} />
      {success && <p className="inline-success">{success}</p>}

      <div className="drawer-actions">
        <button
          type="button"
          className="btn btn-primary"
          onClick={book}
          disabled={busy || (!leadId && !phone.trim())}
        >
          {busy ? 'Booking…' : 'Book appointment'}
        </button>
        {!leadId && !phone.trim() && (
          <span className="muted">Select a lead or enter a phone number to enable booking.</span>
        )}
      </div>
    </Card>
  )
}
