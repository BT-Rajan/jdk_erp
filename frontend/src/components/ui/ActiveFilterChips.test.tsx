import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ActiveFilterChips } from './ActiveFilterChips'

describe('ActiveFilterChips', () => {
  it('renders nothing when there are no active filters', () => {
    const { container } = render(<ActiveFilterChips filters={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders a chip per filter and removes one via its own button', async () => {
    const onRemove = vi.fn()
    render(
      <ActiveFilterChips
        filters={[
          { key: 'status', label: 'Status: Active', onRemove },
          { key: 'search', label: 'Search: acme', onRemove: vi.fn() },
        ]}
      />,
    )
    expect(screen.getByText('Status: Active')).toBeInTheDocument()
    expect(screen.getByText('Search: acme')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Remove Status: Active filter' }))
    expect(onRemove).toHaveBeenCalledOnce()
  })

  it('shows Clear all only when onClearAll is given, and calls it', async () => {
    const onClearAll = vi.fn()
    const { rerender } = render(
      <ActiveFilterChips filters={[{ key: 'status', label: 'Status: Active', onRemove: vi.fn() }]} />,
    )
    expect(screen.queryByRole('button', { name: 'Clear all' })).not.toBeInTheDocument()

    rerender(<ActiveFilterChips filters={[{ key: 'status', label: 'Status: Active', onRemove: vi.fn() }]} onClearAll={onClearAll} />)
    await userEvent.click(screen.getByRole('button', { name: 'Clear all' }))
    expect(onClearAll).toHaveBeenCalledOnce()
  })
})
