import { useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Card, ErrorMessage, LevelBadge } from './ui.jsx'

const LEAD_LABELS = {
  name: 'Name',
  phone: 'Phone',
  budget: 'Budget',
  product_interest: 'Product interest',
  purchase_timeline: 'Timeline',
}

export default function ChatPanel() {
  const [messages, setMessages] = useState([
    {
      role: 'agent',
      text: 'Hi! I am the SalesPilot AI assistant. Tell me what you are looking for and I will help.',
    },
  ])
  const [input, setInput] = useState('')
  const [conversationId, setConversationId] = useState(null)
  const [lead, setLead] = useState(null)
  const [missing, setMissing] = useState(Object.keys(LEAD_LABELS))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const endRef = useRef(null)

  async function send() {
    const text = input.trim()
    if (!text || busy) return
    setError(null)
    setBusy(true)
    setMessages((prev) => [...prev, { role: 'user', text }])
    setInput('')
    try {
      const reply = await api.chat(text, conversationId)
      setConversationId(reply.conversation_id)
      setLead(reply.lead)
      setMissing(reply.missing_fields)
      setMessages((prev) => [...prev, { role: 'agent', text: reply.response }])
    } catch (err) {
      setError(err)
      setMessages((prev) => [
        ...prev,
        { role: 'agent', text: `Sorry, I could not respond. ${err.message}`, failed: true },
      ])
    } finally {
      setBusy(false)
      requestAnimationFrame(() => endRef.current?.scrollIntoView({ behavior: 'smooth' }))
    }
  }

  function reset() {
    setMessages([
      { role: 'agent', text: 'New conversation started. How can I help you today?' },
    ])
    setConversationId(null)
    setLead(null)
    setMissing(Object.keys(LEAD_LABELS))
    setError(null)
  }

  return (
    <div className="chat-layout">
      <Card
        title="Talk to the sales agent"
        subtitle="The agent qualifies the lead and stores everything in MongoDB."
        actions={<button type="button" className="btn btn-ghost" onClick={reset}>New conversation</button>}
        className="chat-card"
      >
        <div className="chat-window">
          {messages.map((message, index) => (
            <div key={index} className={`bubble bubble-${message.role} ${message.failed ? 'bubble-failed' : ''}`}>
              {message.text}
            </div>
          ))}
          {busy && <div className="bubble bubble-agent bubble-typing">…</div>}
          <div ref={endRef} />
        </div>

        <ErrorMessage error={error} />

        <div className="chat-input">
          <input
            placeholder="Type your message…"
            value={input}
            disabled={busy}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') send() }}
          />
          <button type="button" className="btn btn-primary" onClick={send} disabled={busy || !input.trim()}>
            Send
          </button>
        </div>
        <p className="muted mono chat-meta">
          {conversationId ? `conversation: ${conversationId}` : 'new conversation'}
        </p>
      </Card>

      <Card title="Lead progress" subtitle="Fields collected during this conversation." className="lead-card">
        {lead ? (
          <dl className="detail-list">
            {Object.entries(LEAD_LABELS).map(([key, label]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>{lead[key] || <span className="muted">not collected</span>}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="muted">Start chatting to collect lead details.</p>
        )}
        <div className="progress">
          <span className="progress-label">
            {missing.length === 0 ? 'Lead complete' : `${missing.length} field(s) missing`}
          </span>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${((Object.keys(LEAD_LABELS).length - missing.length) / Object.keys(LEAD_LABELS).length) * 100}%` }}
            />
          </div>
        </div>
        {missing.length === 0 && <p><LevelBadge level="HOT" /></p>}
      </Card>
    </div>
  )
}
