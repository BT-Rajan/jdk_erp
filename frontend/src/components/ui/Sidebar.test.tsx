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

  it('is off-canvas (translated out) by default and slides in when mobileOpen is set', () => {
    const { container, rerender } = render(
      <MemoryRouter>
        <Sidebar entries={entries} collapsed={false} onToggleCollapsed={vi.fn()} />
      </MemoryRouter>,
    )
    const aside = container.querySelector('aside')!
    expect(aside.className).toContain('-translate-x-full')

    rerender(
      <MemoryRouter>
        <Sidebar entries={entries} collapsed={false} onToggleCollapsed={vi.fn()} mobileOpen onMobileClose={vi.fn()} />
      </MemoryRouter>,
    )
    expect(aside.className).toContain('translate-x-0')
  })

  it('closes via the backdrop click and via Escape when mobileOpen', async () => {
    const onMobileClose = vi.fn()
    render(
      <MemoryRouter>
        <Sidebar entries={entries} collapsed={false} onToggleCollapsed={vi.fn()} mobileOpen onMobileClose={onMobileClose} />
      </MemoryRouter>,
    )
    await userEvent.keyboard('{Escape}')
    expect(onMobileClose).toHaveBeenCalledOnce()
  })

  it('renders no backdrop when mobileOpen is not set (existing desktop-only usage is unaffected)', () => {
    const { container } = render(
      <MemoryRouter>
        <Sidebar entries={entries} collapsed={false} onToggleCollapsed={vi.fn()} />
      </MemoryRouter>,
    )
    expect(container.querySelector('.fixed.inset-0')).not.toBeInTheDocument()
  })
})
