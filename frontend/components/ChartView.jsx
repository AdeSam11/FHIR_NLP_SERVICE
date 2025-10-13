import React from 'react'
import { Bar } from 'react-chartjs-2'
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend } from 'chart.js'
ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend)

export default function ChartView({ bundle }) {
  const patients = (bundle.entry || []).filter(e => e.resource && e.resource.resourceType === 'Patient').map(e => e.resource)
  const buckets = { '0-17':0, '18-34':0, '35-49':0, '50-64':0, '65+':0 }
  patients.forEach(p => {
    const age = p.age || 0
    if (age <= 17) buckets['0-17']++
    else if (age <= 34) buckets['18-34']++
    else if (age <= 49) buckets['35-49']++
    else if (age <= 64) buckets['50-64']++
    else buckets['65+']++
  })

  const data = {
    labels: Object.keys(buckets),
    datasets: [{ label: 'Patients by age group', data: Object.values(buckets) }]
  }

  return (
    <div style={{ width: 600, marginTop: 12 }}>
      <Bar data={data} />
    </div>
  )
}
