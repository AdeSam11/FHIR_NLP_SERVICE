import React, { useState } from 'react'
import ChartView from '../components/ChartView'
import ResultTable from '../components/ResultTable'

const SUGGESTIONS = [
  'Show me all patients with Hypertension under 50',
  'List female patients aged 30 to 45 with hypertension',
  'List patients above 5 with hypercholesterolemia',
  'Show all male patients burn injuries'
]

// Use an env var in dev/prod, fallback to localhost:8000
const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000'

export default function Home() {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [resp, setResp] = useState(null)
  const [error, setError] = useState(null)

  async function submit() {
    setLoading(true)
    setError(null)
    setResp(null)

    // Abort if taking too long
    const controller = new AbortController()
    const timeoutMs = 60000 // 60seconds
    const timeout = setTimeout(() => controller.abort(), timeoutMs)

    try {
      const r = await fetch(`${API_BASE}/interpret`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
        signal: controller.signal,
      })

      // Status-level handling
      if (!r.ok) {
        // Try to get body text for more context
        let bodyText = ''
        try {
          bodyText = await r.text()
        } catch (e) {
          bodyText = '<could not read response body>'
        }
        // Provide a helpful error message including hints (CORS/Backend)
        const hints = []
        if (r.status === 0) hints.push('Network error or CORS blocked the request (check browser console).')
        if (r.status >= 500) hints.push('Server error — check backend logs.')
        if (r.status === 400) hints.push('Bad request — the backend thinks the input is invalid.')
        setError({
          message: `Backend returned HTTP ${r.status} ${r.statusText}`,
          details: bodyText,
          hints,
        })
        return
      }

      // Try parse JSON safely
      let data = null
      try {
        data = await r.json()
      } catch (e) {
        // If it isn't JSON, show raw text so user/dev can debug
        const raw = await r.text()
        setError({
          message: 'Backend returned non-JSON response',
          details: raw,
          hints: ['Check backend for exceptions (tracebacks) or ensure it returns JSON.'],
        })
        return
      }

      // success
      setResp(data)
    } catch (err) {
      // Distinguish Abort (timeout) from CORS/network errors
      if (err.name === 'AbortError') {
        setError({
          message: 'Request timed out after 60s',
          details: '',
          hints: ['Slow backend, or network issues, Try again'],
        })
      } else {
        // Typically network error or CORS preflight block -> generic network error
        setError({
          message: 'Network error: could not reach backend',
          details: String(err),
          hints: [
            'Is the backend running at ' + API_BASE + '?',
            'If running, check browser console for CORS errors (Access-Control-Allow-Origin).',
            'Try curl to verify the backend (curl -v -X POST ...).'
          ],
        })
      }
    } finally {
      clearTimeout(timeout)
      setLoading(false)
    }
  }

  return (
    <div style={{ padding: 24, fontFamily: 'Inter, system-ui, sans-serif' }}>
      <h1>FHIR NLP Query Test</h1>

      <div style={{ marginBottom: 12 }}>
        <input
          style={{ width: '70%', padding: 8, fontSize: 16 }}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Type a natural-language query (e.g. Show me all patients over 50 with Hypertension)"
        />
        <button onClick={submit} style={{ marginLeft: 8, padding: '8px 12px' }} disabled={loading}>
          {loading ? 'Running...' : 'Run'}
        </button>
      </div>

      <div style={{ marginBottom: 12 }}>
        Suggestions:
        {SUGGESTIONS.map(s => (
          <button key={s} onClick={() => setQuery(s)} style={{ marginLeft: 8 }}>{s}</button>
        ))}
      </div>

      {error && (
        <div style={{ border: '1px solid #f88', padding: 12, marginBottom: 12, background: '#fff6f6' }}>
          <strong style={{ color: '#c00' }}>{error.message}</strong>
          {error.details && <pre style={{ whiteSpace: 'pre-wrap' }}>{error.details}</pre>}
          {error.hints && (
            <div>
              <strong>Hints:</strong>
              <ul>
                {error.hints.map((h, i) => <li key={i}>{h}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      {resp && (
        <div>
          <h2>Interpreted Filters</h2>
          <pre>{JSON.stringify(resp.filters, null, 2)}</pre>

          <h2>Simulated FHIR Requests</h2>
          <pre>{JSON.stringify(resp.fhir_queries, null, 2)}</pre>

          <h2>Results</h2>
          <ChartView bundle={resp} />
          <ResultTable bundle={resp} />
        </div>
      )}
    </div>
  )
}
