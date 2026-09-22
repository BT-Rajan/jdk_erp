import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { CurrencyField } from './CurrencyField'

describe('CurrencyField', () => {
  it('shows the currency symbol and defaults to a 2-decimal step', () => {
    render(<CurrencyField label="Amount" currency="USD" />)
    expect(screen.getByText('$')).toBeInTheDocument()
    const input = screen.getByLabelText('Amount')
    expect(input).toHaveAttribute('type', 'number')
    expect(input).toHaveAttribute('step', '0.01')
  })

  it('shows a different currency symbol when given', () => {
    render(<CurrencyField label="Amount" currency="EUR" />)
    expect(screen.getByText('€')).toBeInTheDocument()
  })

  it('accepts numeric input', async () => {
    render(<CurrencyField label="Amount" />)
    const input = screen.getByLabelText('Amount')
    await userEvent.type(input, '150.50')
    expect(input).toHaveValue(150.5)
  })

  it('shows the visual required indicator without setting the native required attribute', () => {
    const { container } = render(<CurrencyField label="Amount" required />)
    expect(screen.getByLabelText('Amount')).not.toBeRequired()
    expect(container.querySelector('label')?.className).toContain("after:content-['*']")
  })
})
