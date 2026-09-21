import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Drawer } from './Drawer'

describe('Drawer', () => {
  it('renders nothing when closed', () => {
    render(
      <Drawer open={false} title="Order #123" onClose={vi.fn()}>
        content
      </Drawer>,
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders with role/aria-modal/label when open', () => {
    render(
      <Drawer open title="Order #123" onClose={vi.fn()}>
        content
      </Drawer>,
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAttribute('aria-label', 'Order #123')
  })

  it('closes on Escape and via the close button', async () => {
    const onClose = vi.fn()
    render(
      <Drawer open title="Order #123" onClose={onClose}>
        content
      </Drawer>,
    )
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()

    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})
