import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatGrid } from './StatGrid'
import { StatCard } from './StatCard'

describe('StatGrid', () => {
  it('renders its children in a responsive grid', () => {
    render(
      <StatGrid>
        <StatCard label="Open orders" value={42} />
        <StatCard label="Overdue" value={3} />
      </StatGrid>,
    )
    expect(screen.getByText('Open orders')).toBeInTheDocument()
    expect(screen.getByText('Overdue')).toBeInTheDocument()
  })
})
