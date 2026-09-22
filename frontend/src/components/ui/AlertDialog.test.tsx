import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AlertDialog } from './AlertDialog'

describe('AlertDialog', () => {
  it('renders nothing when closed', () => {
    render(<AlertDialog open={false} title="Notice" message="Something happened." onClose={vi.fn()} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('has exactly one action button (acknowledgement, not a decision)', () => {
    render(<AlertDialog open title="Notice" message="Something happened." onClose={vi.fn()} />)
    expect(screen.getAllByRole('button')).toHaveLength(2) // header close (X) + OK
    expect(screen.getByRole('button', { name: 'OK' })).toBeInTheDocument()
  })

  it('calls onClose from the acknowledgement button', async () => {
    const onClose = vi.fn()
    render(<AlertDialog open title="Notice" message="Something happened." onClose={onClose} closeLabel="Got it" />)
    await userEvent.click(screen.getByRole('button', { name: 'Got it' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('shows the message with the given tone', () => {
    render(<AlertDialog open title="Error" message="Failed to save." onClose={vi.fn()} variant="danger" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to save.')
  })
})
