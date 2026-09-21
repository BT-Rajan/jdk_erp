import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { NumberDisplay } from './Number'

describe('NumberDisplay', () => {
  it('adds thousand separators', () => {
    render(<NumberDisplay value={1234567} />)
    expect(screen.getByText('1,234,567')).toBeInTheDocument()
  })

  it('shows the empty placeholder for a missing value', () => {
    render(<NumberDisplay value={undefined} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})
