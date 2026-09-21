import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Percentage } from './Percentage'

describe('Percentage', () => {
  it('formats with one decimal place by default', () => {
    render(<Percentage value={12.5} />)
    expect(screen.getByText('12.5%')).toBeInTheDocument()
  })

  it('shows the empty placeholder for a missing value', () => {
    render(<Percentage value={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})
