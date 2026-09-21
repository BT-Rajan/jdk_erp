import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { CheckboxField } from './CheckboxField'

describe('CheckboxField', () => {
  it('toggles on click, associated via a wrapping label', async () => {
    render(<CheckboxField label="Send welcome email" />)
    const checkbox = screen.getByLabelText('Send welcome email')
    expect(checkbox).not.toBeChecked()
    await userEvent.click(checkbox)
    expect(checkbox).toBeChecked()
  })

  it('shows an error message', () => {
    render(<CheckboxField label="Accept terms" error="You must accept the terms" />)
    expect(screen.getByRole('alert')).toHaveTextContent('You must accept the terms')
  })
})
