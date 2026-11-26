import { useEffect, useState } from 'react'
import { api } from './api/client.js'
import OverviewPanel from './components/OverviewPanel.jsx'
import LeadsPanel from './components/LeadsPanel.jsx'
import CallsPanel from './components/CallsPanel.jsx'
import SummariesPanel from './components/SummariesPanel.jsx'
import AppointmentsPanel from './components/AppointmentsPanel.jsx'
import KnowledgePanel from './components/KnowledgePanel.jsx'
import ChatPanel from './components/ChatPanel.jsx'

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'leads', label: 'Leads' },
  { id: 'calls', label: 'Calls' },
  { id: 'summaries', label: 'Summaries' },
  { id: 'appointments', label: 'Appointments' },
  { id: 'knowledge', label: 'Knowledge Base' },
  { id: 'chat', label: 'AI Chat' },
]

function HealthIndicator() {
  const [health, setHealth] = useState({ state: 'checking' })

  useEffect(() => {
    let active = true
    api
      .health()
      .then((data) => { if (active) setHealth({ state: 'ok', version: data.version }) })
      .catch((error) => { if (active) setHealth({ state: 'down', message: error.message }) })
    return () => { active = false }
  }, [])

  const className =
    health.state === 'ok' ? 'dot dot-ok' : health.state === 'down' ? 'dot dot-down' : 'dot dot-checking'
  const text =
    health.state === 'ok'
      ? `Backend online · v${health.version}`
      : health.state === 'down'
        ? 'Backend unreachable'
        : 'Checking backend…'

  return (
    <span className="health" title={health.message || text}>
      <span className={className} aria-hidden="true" />
      {text}
    </span>
  )
}

export default function App() {
  const [tab, setTab] = useState('overview')

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">SP</span>
          <div>
            <strong>SalesPilot AI</strong>
            <span className="brand-sub">Autonomous Sales Agent</span>
          </div>
        </div>

        <nav className="nav">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item ${tab === item.id ? 'nav-item-active' : ''}`}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <HealthIndicator />
        </div>
      </aside>

      <main className="content">
        <header className="topbar">
          <h1>{TABS.find((item) => item.id === tab)?.label}</h1>
        </header>

        <div className="panel-area">
          {tab === 'overview' && <OverviewPanel onNavigate={setTab} />}
          {tab === 'leads' && <LeadsPanel />}
          {tab === 'calls' && <CallsPanel />}
          {tab === 'summaries' && <SummariesPanel />}
          {tab === 'appointments' && <AppointmentsPanel />}
          {tab === 'knowledge' && <KnowledgePanel />}
          {tab === 'chat' && <ChatPanel />}
        </div>
      </main>
    </div>
  )
}
