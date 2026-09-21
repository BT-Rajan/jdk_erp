import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { NumberField } from './NumberField'

describe('NumberField', () => {
  it('renders a native number input associated with its label', () => {
    render(<NumberField label="Quantity" />)
    expect(screen.getByLabelText('Quantity')).toHaveAttribute('type', 'number')
  })

  it('clamps to max on blur', async () => {
    render(<NumberField label="Discount %" min={0} max={100} />)
    const input = screen.getByLabelText('Discount %')
    await userEvent.type(input, '150')
    await userEvent.tab()
    expect(input).toHaveValue(100)
  })

  it('clamps to min on blur', async () => {
    render(<NumberField label="Quantity" min={0} max={100} />)
    const input = screen.getByLabelText('Quantity')
    await userEvent.type(input, '-5')
    await userEvent.tab()
    expect(input).toHaveValue(0)
  })

  it('leaves in-range values untouched', async () => {
    render(<NumberField label="Quantity" min={0} max={100} />)
    const input = screen.getByLabelText('Quantity')
    await userEvent.type(input, '42')
    await userEvent.tab()
    expect(input).toHaveValue(42)
  })
})
