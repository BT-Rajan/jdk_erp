import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BarChart } from './BarChart'

const data = [
  { category: 'Raw materials', budget: 100, actual: 80 },
  { category: 'Labour', budget: 200, actual: 220 },
]

describe('BarChart', () => {
  it('shows loading/error/empty states', () => {
    const { rerender } = render(<BarChart data={data} xKey="category" series={[{ key: 'budget', label: 'Budget' }]} loading />)
    expect(screen.getByRole('status')).toBeInTheDocument()

    rerender(<BarChart data={data} xKey="category" series={[{ key: 'budget', label: 'Budget' }]} error="Failed" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Failed')

    rerender(<BarChart data={[]} xKey="category" series={[{ key: 'budget', label: 'Budget' }]} />)
    expect(screen.getByText('No data')).toBeInTheDocument()
  })

  it('renders grouped bars by default and a legend entry per series', () => {
    render(
      <BarChart
        data={data}
        xKey="category"
        series={[
          { key: 'budget', label: 'Budget' },
          { key: 'actual', label: 'Actual' },
        ]}
      />,
    )
    expect(screen.getByText('Budget')).toBeInTheDocument()
    expect(screen.getByText('Actual')).toBeInTheDocument()
  })

  it('renders without crashing when stacked is set', () => {
    render(
      <BarChart
        data={data}
        xKey="category"
        stacked
        series={[
          { key: 'budget', label: 'Budget' },
          { key: 'actual', label: 'Actual' },
        ]}
      />,
    )
    expect(document.querySelector('svg.recharts-surface')).toBeInTheDocument()
  })
})
