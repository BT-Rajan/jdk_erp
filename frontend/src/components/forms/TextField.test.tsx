import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { TextField } from './TextField'

describe('TextField', () => {
  it('associates the label with the input via a generated id', () => {
    render(<TextField label="Full name" />)
    expect(screen.getByLabelText('Full name')).toBeInTheDocument()
  })

  it('shows an error with role=alert and marks the input invalid, wired via aria-describedby', () => {
    render(<TextField label="Email" error="Email is required" />)
    const input = screen.getByLabelText('Email')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    const error = screen.getByRole('alert')
    expect(error).toHaveTextContent('Email is required')
    expect(input).toHaveAttribute('aria-describedby', error.id)
  })

  it('shows a hint when there is no error', () => {
    render(<TextField label="Email" hint="We will never share this" />)
    expect(screen.getByText('We will never share this')).toBeInTheDocument()
  })

  it('accepts typed input', async () => {
    render(<TextField label="Full name" />)
    await userEvent.type(screen.getByLabelText('Full name'), 'Ada Lovelace')
    expect(screen.getByLabelText('Full name')).toHaveValue('Ada Lovelace')
  })
})
