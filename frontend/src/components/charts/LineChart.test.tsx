import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LineChart } from './LineChart'

const data = [
  { month: 'Jan', revenue: 100, cost: 60 },
  { month: 'Feb', revenue: 150, cost: 80 },
]

describe('LineChart', () => {
  it('shows a spinner while loading, not the chart', () => {
    render(<LineChart data={data} xKey="month" series={[{ key: 'revenue', label: 'Revenue' }]} loading />)
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(document.querySelector('svg.recharts-surface')).not.toBeInTheDocument()
  })

  it('shows an error alert instead of the chart', () => {
    render(<LineChart data={data} xKey="month" series={[{ key: 'revenue', label: 'Revenue' }]} error="Failed to load" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load')
  })

  it('shows the empty state when there is no data', () => {
    render(<LineChart data={[]} xKey="month" series={[{ key: 'revenue', label: 'Revenue' }]} emptyMessage="Nothing yet" />)
    expect(screen.getByText('No data')).toBeInTheDocument()
    expect(screen.getByText('Nothing yet')).toBeInTheDocument()
  })

  it('renders a chart with a legend entry per series when there is data', () => {
    render(
      <LineChart
        data={data}
        xKey="month"
        series={[
          { key: 'revenue', label: 'Revenue' },
          { key: 'cost', label: 'Cost' },
        ]}
      />,
    )
    expect(document.querySelector('svg.recharts-surface')).toBeInTheDocument()
    expect(screen.getByText('Revenue')).toBeInTheDocument()
    expect(screen.getByText('Cost')).toBeInTheDocument()
  })
})
