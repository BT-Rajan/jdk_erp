import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Badge, StatusBadge } from './Badge'

describe('Badge', () => {
  it('renders its text', () => {
    render(<Badge tone="success">Paid</Badge>)
    expect(screen.getByText('Paid')).toBeInTheDocument()
  })
})

describe('StatusBadge', () => {
  it('resolves tone from a caller-supplied, domain-scoped map', () => {
    render(<StatusBadge status="overdue" toneMap={{ overdue: 'danger', paid: 'success' }} />)
    expect(screen.getByText('overdue')).toBeInTheDocument()
  })

  it('falls back to neutral for an unmapped status instead of throwing', () => {
    render(<StatusBadge status="unknown_status" toneMap={{ paid: 'success' }} />)
    expect(screen.getByText('unknown_status')).toBeInTheDocument()
  })
})
