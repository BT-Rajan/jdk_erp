import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppLayout } from './AppLayout'

const { useAuthMock, logoutMock, apiGetMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  logoutMock: vi.fn(),
  apiGetMock: vi.fn(),
}))
vi.mock('@/lib/auth/AuthContext', () => ({ useAuth: useAuthMock }))
// AppLayout renders NotificationBell, which polls
// GET /api/notifications/unread-count on mount -- mocked here so this
// test exercises the layout, not a real network call against a backend
// that doesn't exist in this environment.
vi.mock('@/lib/apiClient', () => ({ apiClient: { get: apiGetMock, post: vi.fn(), patch: vi.fn() } }))

beforeEach(() => {
  logoutMock.mockReset()
  apiGetMock.mockReset().mockResolvedValue({ data: { count: 0 } })
  useAuthMock.mockReturnValue({ user: { id: 1, full_name: 'Ada Lovelace', role: 'admin' }, logout: logoutMock })
})

describe('AppLayout', () => {
  it("shows the signed-in user's name and role, and renders the routed page in the outlet", () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<AppLayout />}>
            <Route index element={<p>Dashboard content</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument()
    expect(screen.getByText('admin')).toBeInTheDocument()
    expect(screen.getByText('Dashboard content')).toBeInTheDocument()
  })

  it('calls logout when "Sign out" is chosen from the account menu', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<AppLayout />}>
            <Route index element={<p>Dashboard content</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Account' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Sign out' }))

    expect(logoutMock).toHaveBeenCalledOnce()
  })

  it('has one menu (the sidebar), an icon-only home link in the header, and Master Data under Settings', async () => {
    renderLayout()

    expect(screen.getAllByRole('navigation', { name: 'Main' })).toHaveLength(1)
    const header = screen.getByRole('banner')
    const home = within(header).getByRole('link', { name: 'Dashboard' })
    expect(home).toHaveAttribute('href', '/')
    expect(home).not.toHaveTextContent('Dashboard')
    expect(screen.queryByRole('button', { name: /master data/i })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /settings/i }))
    expect(screen.getByRole('link', { name: 'Customers' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Working calendar' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'AI Assistant' })).toBeInTheDocument()
    expect(within(header).getByRole('button', { name: 'Open JDK Assistant' })).toBeInTheDocument()
  })

  it('still gives non-admins the Master Data pages under Settings, without the admin pages', async () => {
    useAuthMock.mockReturnValue({ user: { id: 2, full_name: 'Sam Sales', role: 'team_member' }, logout: logoutMock })
    renderLayout()

    await userEvent.click(screen.getByRole('button', { name: /settings/i }))
    expect(screen.getByRole('link', { name: 'Customers' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Products' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Working calendar' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'AI Assistant' })).not.toBeInTheDocument()
  })
})

function renderLayout() {
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<AppLayout />}>
          <Route index element={<p>Dashboard content</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}
