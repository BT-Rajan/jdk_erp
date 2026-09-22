import { render, screen } from '@testing-library/react'
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
})
