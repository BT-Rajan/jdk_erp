import { useRef } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Modal } from './Modal'

describe('Modal', () => {
  it('renders nothing when closed', () => {
    render(
      <Modal open={false} title="Edit user" onClose={vi.fn()}>
        content
      </Modal>,
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders with the right role/aria-modal/label when open', () => {
    render(
      <Modal open title="Edit user" onClose={vi.fn()}>
        <input placeholder="Name" />
      </Modal>,
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAttribute('aria-label', 'Edit user')
  })

  it('auto-focuses the first focusable element on open (the header Close button, which renders before the body)', () => {
    render(
      <Modal open title="Edit user" onClose={vi.fn()}>
        <input placeholder="Name" />
      </Modal>,
    )
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
  })

  it('closes on Escape', async () => {
    const onClose = vi.fn()
    render(
      <Modal open title="Edit user" onClose={onClose}>
        content
      </Modal>,
    )
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('closes on backdrop click but not on click inside the dialog', async () => {
    const onClose = vi.fn()
    render(
      <Modal open title="Edit user" onClose={onClose}>
        <button type="button">Inside</button>
      </Modal>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Inside' }))
    expect(onClose).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('dialog').parentElement!)
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('closes via the header close button', async () => {
    const onClose = vi.fn()
    render(
      <Modal open title="Edit user" onClose={onClose}>
        content
      </Modal>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('honors an initialFocusRef override instead of the first focusable element', () => {
    function Fixture() {
      const cancelRef = useRef<HTMLButtonElement>(null)
      return (
        <Modal open title="Delete user" onClose={vi.fn()} initialFocusRef={cancelRef}>
          <button type="button">First in DOM order</button>
          <button type="button" ref={cancelRef}>
            Cancel
          </button>
        </Modal>
      )
    }
    render(<Fixture />)
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
  })
})
