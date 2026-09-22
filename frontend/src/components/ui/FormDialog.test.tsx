import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { FormDialog } from './FormDialog'
import { TextField } from '@/components/forms/TextField'

describe('FormDialog', () => {
  it('renders nothing when closed', () => {
    render(
      <FormDialog open={false} title="New supplier" onClose={vi.fn()} onSubmit={vi.fn()}>
        <TextField label="Name" />
      </FormDialog>,
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('submits the form when Save (in the footer) is clicked, via the native form attribute', async () => {
    const onSubmit = vi.fn((event) => event.preventDefault())
    render(
      <FormDialog open title="New supplier" onClose={vi.fn()} onSubmit={onSubmit}>
        <TextField label="Name" />
      </FormDialog>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenCalledOnce()
  })

  it('calls onClose from Cancel, and disables Cancel while submitting', () => {
    const onClose = vi.fn()
    render(
      <FormDialog open title="New supplier" onClose={onClose} onSubmit={vi.fn()} submitting>
        <TextField label="Name" />
      </FormDialog>,
    )
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('aria-busy', 'true')
  })

  it('renders children inside the form', () => {
    render(
      <FormDialog open title="New supplier" onClose={vi.fn()} onSubmit={vi.fn()}>
        <TextField label="Name" />
      </FormDialog>,
    )
    expect(screen.getByLabelText('Name')).toBeInTheDocument()
  })
})
