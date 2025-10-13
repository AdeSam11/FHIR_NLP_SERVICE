import React from 'react'

export default function ResultTable({ bundle }) {
  const patients = (bundle.entry || []).filter(e => e.resource && e.resource.resourceType === 'Patient').map(e => e.resource)

  return (
    <div style={{ marginTop: 12 }}>
      <table border={1} cellPadding={8} style={{ borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th>Name</th>
            <th>Age</th>
            <th>Gender</th>
            <th>BirthDate</th>
          </tr>
        </thead>
        <tbody>
          {patients.map(p => (
            <tr key={p.id}>
              <td>{(p.name && p.name[0]) ? p.name[0].given[0] + ' ' + p.name[0].family : p.id}</td>
              <td>{p.age}</td>
              <td>{p.gender}</td>
              <td>{p.birthDate}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
