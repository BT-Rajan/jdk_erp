import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { BulkActionsBar } from './BulkActionsBar'

describe('BulkActionsBar', () => {
  it('renders nothing when count is 0', () => {
    const { container } = render(<BulkActionsBar count={0} onClear={vi.fn()} actions={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the selection count and calls actions/onClear', async () => {
    const onSelect = vi.fn()
    const onClear = vi.fn()
    render(
      <BulkActionsBar
        count={3}
        onClear={onClear}
        actions={[{ key: 'delete', label: 'Delete', onSelect, danger: true }]}
      />,
    )
    expect(screen.getByText('3 selected')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onSelect).toHaveBeenCalledOnce()

    await userEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(onClear).toHaveBeenCalledOnce()
  })
})
