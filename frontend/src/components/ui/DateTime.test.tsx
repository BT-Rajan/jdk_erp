import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DateTime } from './DateTime'

describe('DateTime', () => {
  it('renders date-only by default', () => {
    render(<DateTime value={new Date(2026, 0, 5)} />)
    expect(screen.getByText('05/01/2026')).toBeInTheDocument()
  })

  it('renders date and time when withTime is set', () => {
    render(<DateTime value={new Date(2026, 0, 5, 9, 30)} withTime />)
    expect(screen.getByText('05/01/2026 09:30')).toBeInTheDocument()
  })
})
