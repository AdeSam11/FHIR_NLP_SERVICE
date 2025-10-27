import React from 'react'

/**
 * Normalize whatever bundle is into an array of summarized patients:
 * Each patient: { id, name, gender, birthDate, age, conditions }
 */
function normalizePatients(bundle) {
  if (!bundle) return []

  // If bundle is already an array of summarized patients
  if (Array.isArray(bundle)) {
    return bundle.map(p => summarizeIfNeeded(p)).filter(Boolean)
  }

  // If bundle.patients is present (our backend summarized format)
  if (Array.isArray(bundle.patients)) {
    return bundle.patients.map(p => summarizeIfNeeded(p)).filter(Boolean)
  }

  // If raw FHIR bundle with entry[] resources
  if (Array.isArray(bundle.entry)) {
    const patients = bundle.entry
      .map(e => (e && e.resource && e.resource.resourceType === 'Patient' ? e.resource : null))
      .filter(Boolean)
    return patients.map(p => summarizeIfNeeded(p))
  }

  // If the backend wrapped the patients under results.patients
  if (bundle.results && Array.isArray(bundle.results.patients)) {
    return bundle.results.patients.map(p => summarizeIfNeeded(p)).filter(Boolean)
  }

  // Unexpected shape -> return empty
  return []
}

function summarizeIfNeeded(p) {
  if (!p) return null
  // If already summarized (has id and name keys)
  if (p.id && (p.name || p.birthDate || p.gender || p.age !== undefined)) {
    // ensure name string present
    const name = typeof p.name === 'string' ? p.name : buildNameFromResource(p)
    return {
      id: p.id,
      name,
      gender: p.gender || '',
      birthDate: p.birthDate || '',
      age: typeof p.age === 'number' ? p.age : computeAge(p.birthDate),
      conditions: p.conditions || []
    }
  }

  // Otherwise assume it's a full FHIR Patient resource
  const id = p.id || (p.resource && p.resource.id) || ''
  const resource = p.resource || p
  const name = buildNameFromResource(resource)
  const birthDate = resource.birthDate || ''
  const gender = resource.gender || ''
  const age = computeAge(birthDate)

  return { id, name, gender, birthDate, age, conditions: resource.conditions || [] }
}

function buildNameFromResource(r) {
  if (!r) return ''
  // If already a string
  if (typeof r.name === 'string') return r.name
  if (Array.isArray(r.name) && r.name[0]) {
    const given = (r.name[0].given && r.name[0].given[0]) || ''
    const family = r.name[0].family || ''
    return `${given} ${family}`.trim() || r.id || ''
  }
  // sometimes name can be object with given/family
  if (r.given || r.family) {
    return `${r.given || ''} ${r.family || ''}`.trim()
  }
  return r.id || ''
}

function computeAge(birthDate) {
  if (!birthDate) return ''
  try {
    const year = parseInt(String(birthDate).split('-')[0], 10)
    if (Number.isNaN(year)) return ''
    return new Date().getFullYear() - year
  } catch {
    return ''
  }
}

export default function ResultTable({ bundle }) {
  const patients = normalizePatients(bundle)

  return (
    <div style={{ marginTop: 12 }}>
      {patients.length === 0 ? (
        <div style={{ padding: 12, background: '#fff8e6', border: '1px solid #ffd08a' }}>
          No patients found.
        </div>
      ) : (
        <table border={1} cellPadding={8} style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Age</th>
              <th>Gender</th>
              <th>BirthDate</th>
              <th>Conditions</th>
            </tr>
          </thead>
          <tbody>
            {patients.map(p => (
              <tr key={p.id || Math.random()}>
                <td>{p.name}</td>
                <td>{p.age}</td>
                <td>{p.gender}</td>
                <td>{p.birthDate}</td>
                <td>{Array.isArray(p.conditions) ? p.conditions.join(', ') : p.conditions || ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
