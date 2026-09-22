import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PieChart } from './PieChart'

const data = [
  { status: 'Paid', count: 12 },
  { status: 'Overdue', count: 3 },
]

describe('PieChart', () => {
  it('shows loading/error/empty states', () => {
    const { rerender } = render(<PieChart data={data} nameKey="status" valueKey="count" loading />)
    expect(screen.getByRole('status')).toBeInTheDocument()

    rerender(<PieChart data={data} nameKey="status" valueKey="count" error="Failed" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Failed')

    rerender(<PieChart data={[]} nameKey="status" valueKey="count" />)
    expect(screen.getByText('No data')).toBeInTheDocument()
  })

  it('renders with a legend entry per data point', () => {
    render(<PieChart data={data} nameKey="status" valueKey="count" />)
    expect(screen.getByText('Paid')).toBeInTheDocument()
    expect(screen.getByText('Overdue')).toBeInTheDocument()
  })

  it('renders as a donut without crashing', () => {
    render(<PieChart data={data} nameKey="status" valueKey="count" donut />)
    expect(document.querySelector('svg.recharts-surface')).toBeInTheDocument()
  })
})
