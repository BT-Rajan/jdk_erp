import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Currency } from './Currency'

describe('Currency', () => {
  it('formats using the given currency', () => {
    render(<Currency value={99.9} currency="USD" />)
    expect(screen.getByText('$99.90')).toBeInTheDocument()
  })

  it('shows the empty placeholder for a missing value', () => {
    render(<Currency value={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})
