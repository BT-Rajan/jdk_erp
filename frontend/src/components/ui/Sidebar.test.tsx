import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { Sidebar } from './Sidebar'
import type { NavEntry } from './nav-types'

const entries: NavEntry[] = [
  { type: 'leaf', label: 'Dashboard', to: '/' },
  {
    type: 'group',
    label: 'Master Data',
    items: [{ label: 'Suppliers', to: '/suppliers' }],
  },
]

describe('Sidebar', () => {
  it('renders leaf links and toggles a group open to reveal its items', async () => {
    render(
      <MemoryRouter>
        <Sidebar entries={entries} collapsed={false} onToggleCollapsed={vi.fn()} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('href', '/')
    expect(screen.queryByRole('link', { name: 'Suppliers' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Master Data' }))
    expect(screen.getByRole('link', { name: 'Suppliers' })).toHaveAttribute('href', '/suppliers')
  })

  it('calls onToggleCollapsed from the collapse button', async () => {
    const onToggleCollapsed = vi.fn()
    render(
      <MemoryRouter>
        <Sidebar entries={entries} collapsed={false} onToggleCollapsed={onToggleCollapsed} />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(onToggleCollapsed).toHaveBeenCalledOnce()
  })

  it('renders leaf entries with an accessible label when collapsed to icon-only', () => {
    render(
      <MemoryRouter>
        <Sidebar entries={entries} collapsed onToggleCollapsed={vi.fn()} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
  })
})
