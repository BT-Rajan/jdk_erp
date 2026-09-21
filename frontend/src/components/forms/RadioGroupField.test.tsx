import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { RadioGroupField } from './RadioGroupField'

describe('RadioGroupField', () => {
  it('renders a labeled radiogroup and allows selecting one option', async () => {
    render(
      <RadioGroupField
        label="Payment terms"
        name="terms"
        options={[
          { value: 'net30', label: 'Net 30' },
          { value: 'net60', label: 'Net 60' },
        ]}
      />,
    )
    const group = screen.getByRole('radiogroup', { name: 'Payment terms' })
    expect(group).toBeInTheDocument()

    const net60 = screen.getByRole('radio', { name: 'Net 60' })
    await userEvent.click(net60)
    expect(net60).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Net 30' })).not.toBeChecked()
  })
})
