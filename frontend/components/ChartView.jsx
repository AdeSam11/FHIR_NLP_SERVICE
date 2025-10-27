import React from 'react'
import { Bar } from 'react-chartjs-2'
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend } from 'chart.js'
ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend)

/* reuse normalization logic similar to ResultTable */
function normalizePatients(bundle) {
  if (!bundle) return []
  if (Array.isArray(bundle)) return bundle.map(summarizeIfNeeded).filter(Boolean)
  if (Array.isArray(bundle.patients)) return bundle.patients.map(summarizeIfNeeded).filter(Boolean)
  if (Array.isArray(bundle.entry)) {
    const pats = bundle.entry.map(e => (e && e.resource && e.resource.resourceType === 'Patient' ? e.resource : null)).filter(Boolean)
    return pats.map(summarizeIfNeeded)
  }
  if (bundle.results && Array.isArray(bundle.results.patients)) {
    return bundle.results.patients.map(summarizeIfNeeded).filter(Boolean)
  }
  return []
}

function summarizeIfNeeded(p) {
  if (!p) return null
  if (p.id && (p.name || p.birthDate || p.gender || p.age !== undefined)) {
    return {
      id: p.id,
      name: typeof p.name === 'string' ? p.name : buildNameFromResource(p),
      gender: p.gender || '',
      birthDate: p.birthDate || '',
      age: typeof p.age === 'number' ? p.age : computeAge(p.birthDate)
    }
  }
  const resource = p.resource || p
  const id = resource.id || ''
  const name = buildNameFromResource(resource)
  const birthDate = resource.birthDate || ''
  const gender = resource.gender || ''
  const age = computeAge(birthDate)
  return { id, name, gender, birthDate, age }
}

function buildNameFromResource(r) {
  if (!r) return ''
  if (typeof r.name === 'string') return r.name
  if (Array.isArray(r.name) && r.name[0]) {
    const given = (r.name[0].given && r.name[0].given[0]) || ''
    const family = r.name[0].family || ''
    return `${given} ${family}`.trim() || r.id || ''
  }
  if (r.given || r.family) return `${r.given || ''} ${r.family || ''}`.trim()
  return r.id || ''
}

function computeAge(birthDate) {
  if (!birthDate) return 0
  const year = parseInt(String(birthDate).split('-')[0], 10)
  if (Number.isNaN(year)) return 0
  return new Date().getFullYear() - year
}

export default function ChartView({ bundle }) {
  const patients = normalizePatients(bundle)

  const buckets = { '0-17': 0, '18-34': 0, '35-49': 0, '50-64': 0, '65+': 0 }
  patients.forEach(p => {
    const age = typeof p.age === 'number' ? p.age : 0
    if (age <= 17) buckets['0-17']++
    else if (age <= 34) buckets['18-34']++
    else if (age <= 49) buckets['35-49']++
    else if (age <= 64) buckets['50-64']++
    else buckets['65+']++
  })

  const total = Object.values(buckets).reduce((a, b) => a + b, 0)
  const data = {
    labels: Object.keys(buckets),
    datasets: [{ label: 'Patients by age group', data: Object.values(buckets) }]
  }

  return (
    <div style={{ width: 600, marginTop: 12 }}>
      {total === 0 ? (
        <div style={{ padding: 12, background: '#f6f8fa', border: '1px solid #e1e4e8' }}>
          No patients to chart.
        </div>
      ) : (
        <Bar data={data} />
      )}
    </div>
  )
}
