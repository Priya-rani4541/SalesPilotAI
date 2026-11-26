import { useRef, useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../hooks/useAsync.js'
import {
  Card,
  EmptyState,
  ErrorBanner,
  ErrorMessage,
  Spinner,
  formatDateTime,
} from './ui.jsx'

export default function KnowledgePanel() {
  const documents = useAsync(() => api.listDocuments(), [])
  const docs = documents.data?.documents || []

  return (
    <div className="stack">
      <UploadCard onUploaded={documents.reload} />

      <Card
        title="Knowledge base"
        subtitle={documents.data ? `${documents.data.total} document(s) indexed.` : 'PDFs indexed into the FAISS vector store.'}
        actions={<button type="button" className="btn btn-ghost" onClick={documents.reload}>Refresh</button>}
      >
        {documents.loading && <Spinner label="Loading documents…" />}
        {documents.error && <ErrorBanner error={documents.error} onRetry={documents.reload} />}
        {!documents.loading && !documents.error && docs.length === 0 && (
          <EmptyState message="No documents indexed yet. Upload a PDF above." />
        )}
        {!documents.loading && !documents.error && docs.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Pages</th>
                  <th>Chunks</th>
                  <th>Indexed</th>
                </tr>
              </thead>
              <tbody>
                {docs.map((doc) => (
                  <tr key={doc.id}>
                    <td>{doc.filename}</td>
                    <td>{doc.pages}</td>
                    <td>{doc.chunks}</td>
                    <td>{formatDateTime(doc.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <QueryCard />
    </div>
  )
}

function UploadCard({ onUploaded }) {
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  async function upload() {
    if (!file) return
    setBusy(true)
    setError(null)
    setSuccess(null)
    try {
      const result = await api.uploadDocument(file)
      setSuccess(result.message)
      setFile(null)
      if (inputRef.current) inputRef.current.value = ''
      onUploaded()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card
      title="Upload a PDF"
      subtitle="The PDF is split into overlapping chunks, embedded with Gemini and stored in FAISS."
    >
      <div className="filters">
        <label className="field field-grow">
          <span>PDF file (max 15 MB)</span>
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
        </label>
        <button type="button" className="btn btn-primary" onClick={upload} disabled={busy || !file}>
          {busy ? 'Uploading…' : 'Upload & index'}
        </button>
      </div>
      <ErrorMessage error={error} />
      {success && <p className="inline-success">{success}</p>}
    </Card>
  )
}

function QueryCard() {
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  async function ask() {
    if (!question.trim()) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setResult(await api.queryKnowledge(question.trim()))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card
      title="Ask the knowledge base"
      subtitle="Answers are grounded strictly in the indexed documents; unrelated questions get a fallback reply."
    >
      <div className="filters">
        <label className="field field-grow">
          <span>Question</span>
          <input
            placeholder="What is our refund policy?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') ask() }}
          />
        </label>
        <button type="button" className="btn btn-primary" onClick={ask} disabled={busy || !question.trim()}>
          {busy ? 'Searching…' : 'Ask'}
        </button>
      </div>

      <ErrorMessage error={error} />

      {result && (
        <div className="block callout">
          <p className="lead-text">{result.answer}</p>
          <p className="muted">
            {result.found
              ? `Grounded in ${result.sources.length} chunk(s) · model: ${result.model}`
              : `No relevant context found · model: ${result.model}`}
          </p>
          {result.sources.length > 0 && (
            <details className="sources">
              <summary>View sources</summary>
              <ul className="bullets">
                {result.sources.map((source, index) => (
                  <li key={index}>
                    <strong>{source.filename}</strong>
                    {source.page ? ` (page ${source.page})` : ''} · score {source.score.toFixed(2)}
                    <p className="muted">{source.text}</p>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </Card>
  )
}
