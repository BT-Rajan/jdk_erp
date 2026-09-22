import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { TopNav } from './TopNav'
import type { NavEntry } from './nav-types'

const entries: NavEntry[] = [
  { type: 'leaf', label: 'Dashboard', to: '/' },
  {
    type: 'group',
    label: 'Admin',
    items: [
      { label: 'Users', to: '/admin/users' },
      { label: 'Settings', to: '/admin/settings' },
    ],
  },
]

describe('TopNav', () => {
  it('renders leaf entries as direct links', () => {
    render(
      <MemoryRouter>
        <TopNav logo={<span>Logo</span>} entries={entries} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('href', '/')
  })

  it('opens a group as a dropdown of links, closes on outside click', async () => {
    render(
      <MemoryRouter>
        <div>
          <button type="button">Outside</button>
          <TopNav logo={<span>Logo</span>} entries={entries} />
        </div>
      </MemoryRouter>,
    )
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Admin' }))
    expect(screen.getByRole('menu', { name: 'Admin' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Users' })).toHaveAttribute('href', '/admin/users')

    await userEvent.click(screen.getByRole('button', { name: 'Outside' }))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('renders slotted actions', () => {
    render(
      <MemoryRouter>
        <TopNav logo={<span>Logo</span>} entries={entries} actions={<button type="button">Sign out</button>} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
  })

  it('hides the inline entries list below md -- mobile navigation goes through a Sidebar/hamburger instead', () => {
    render(
      <MemoryRouter>
        <TopNav logo={<span>Logo</span>} entries={entries} />
      </MemoryRouter>,
    )
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(nav.className).toContain('hidden')
    expect(nav.className).toContain('md:block')
  })
})
