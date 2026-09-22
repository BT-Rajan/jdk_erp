import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { FormActions } from './FormActions'

describe('FormActions', () => {
  it('calls onCancel from the Cancel button', async () => {
    const onCancel = vi.fn()
    render(<FormActions onCancel={onCancel} />)
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('the Save button is type=submit, not a click handler', () => {
    render(<FormActions onCancel={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('type', 'submit')
  })

  it('disables Cancel and shows Save as loading while submitting', () => {
    render(<FormActions onCancel={vi.fn()} submitting />)
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('aria-busy', 'true')
  })

  it('supports custom labels', () => {
    render(<FormActions onCancel={vi.fn()} cancelLabel="Discard" submitLabel="Create" />)
    expect(screen.getByRole('button', { name: 'Discard' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create' })).toBeInTheDocument()
  })

  it('associates Save with a form elsewhere in the DOM via formId', () => {
    render(<FormActions onCancel={vi.fn()} formId="my-form" />)
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('form', 'my-form')
  })
})
