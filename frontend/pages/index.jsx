import React, { useState } from 'react'
import ChartView from '../components/ChartView'
import ResultTable from '../components/ResultTable'

const SUGGESTIONS = [
  'Show me all diabetic patients over 50',
  'List female patients aged 30 to 45 with hypertension',
  'Find patients under 18 with asthma',
  'Show male patients with diabetes and hypertension'
]

export default function Home() {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [resp, setResp] = useState(null)

  async function submit() {
    setLoading(true)
    try {
      const r = await fetch('http://localhost:8000/interpret', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query })
      })
      const data = await r.json()
      setResp(data)
    } catch (err) {
      console.error(err)
      alert('Error connecting to backend. Start the backend at http://localhost:8000')
    } finally {
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
          placeholder="Type a natural-language query (e.g. Show me all diabetic patients over 50)"
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

      {resp && (
        <div>
          <h2>Interpreted Filters</h2>
          <pre>{JSON.stringify(resp.filters, null, 2)}</pre>

          <h2>Simulated FHIR Requests</h2>
          <pre>{JSON.stringify(resp.fhir_queries, null, 2)}</pre>

          <h2>Results</h2>
          <ChartView bundle={resp.results} />
          <ResultTable bundle={resp.results} />
        </div>
      )}
    </div>
  )
}
