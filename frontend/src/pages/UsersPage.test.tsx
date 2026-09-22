import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { UsersPage } from './UsersPage'

const { useAuthMock, getMock, postMock, patchMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  getMock: vi.fn(),
  postMock: vi.fn(),
  patchMock: vi.fn(),
}))

vi.mock('@/lib/auth/AuthContext', () => ({ useAuth: useAuthMock }))
vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock, patch: patchMock } }
})

const ADMIN = { id: 1, full_name: 'Admin User', role: 'admin' }

const TEAMS_RESPONSE = {
  data: [{ id: 1, organisation_id: 1, name: 'Sales', code: 'SALES', description: null, is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}

function makeUser(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    organisation_id: 1,
    full_name: 'Ada Lovelace',
    email: 'ada@example.com',
    username: 'ada',
    is_active: true,
    last_login_at: null,
    role: 'admin',
    team_ids: [],
    ...overrides,
  }
}

function usersResponse(data: ReturnType<typeof makeUser>[], overrides: Partial<{ page: number; page_size: number; total: number; total_pages: number }> = {}) {
  return {
    data,
    pagination: { page: 1, page_size: 20, total: data.length, total_pages: 1, ...overrides },
  }
}

beforeEach(() => {
  useAuthMock.mockReset().mockReturnValue({ user: ADMIN })
  getMock.mockReset()
  postMock.mockReset()
  patchMock.mockReset()

  getMock.mockImplementation((url: string) => {
    if (url === '/api/teams') return Promise.resolve({ data: TEAMS_RESPONSE })
    if (url === '/api/users') return Promise.resolve({ data: usersResponse([makeUser()]) })
    return Promise.reject(new Error(`Unexpected GET ${url}`))
  })
})

describe('UsersPage', () => {
  it('shows AccessDeniedState for a non-admin instead of the table', () => {
    useAuthMock.mockReturnValue({ user: { id: 2, full_name: 'Team Member', role: 'team_member' } })
    render(<UsersPage />)

    expect(screen.getByText('Access denied')).toBeInTheDocument()
    expect(getMock).not.toHaveBeenCalled()
  })

  it('loads and renders users on mount, with exactly one initial request', async () => {
    render(<UsersPage />)

    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument()
    const userCalls = getMock.mock.calls.filter(([url]) => url === '/api/users')
    expect(userCalls).toHaveLength(1)
  })

  it('shows the loading state while the request is in flight', async () => {
    let resolveUsers!: (value: unknown) => void
    getMock.mockImplementation((url: string) => {
      if (url === '/api/teams') return Promise.resolve({ data: TEAMS_RESPONSE })
      return new Promise((resolve) => {
        resolveUsers = resolve
      })
    })

    render(<UsersPage />)
    expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument()
    resolveUsers({ data: usersResponse([makeUser()]) })
    await screen.findByText('Ada Lovelace')
  })

  it('shows an error state when the request fails', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/teams') return Promise.resolve({ data: TEAMS_RESPONSE })
      return Promise.reject(new Error('Network down'))
    })

    render(<UsersPage />)
    expect(await screen.findByText('Network down')).toBeInTheDocument()
  })

  it('shows a distinct empty state for no users at all vs. no search matches', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/teams') return Promise.resolve({ data: TEAMS_RESPONSE })
      return Promise.resolve({ data: usersResponse([]) })
    })

    render(<UsersPage />)
    expect(await screen.findByText('No users yet')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Search'), 'zzz')
    await waitFor(() => expect(screen.getByText('No matching users')).toBeInTheDocument())
  })

  it('debounces search: types quickly but only fires one request with the final term, resetting to page 1', async () => {
    render(<UsersPage />)
    await screen.findByText('Ada Lovelace')
    getMock.mockClear()

    const search = screen.getByLabelText('Search')
    await userEvent.type(search, 'ada')

    await waitFor(() => {
      const calls = getMock.mock.calls.filter(([url]) => url === '/api/users')
      expect(calls).toHaveLength(1)
    })
    const [, config] = getMock.mock.calls.find(([url]) => url === '/api/users')!
    expect(config.params.q).toBe('ada')
    expect(config.params.page).toBe(1)
  })

  it('clicking a sortable column header requests that field, then flips direction on a second click', async () => {
    render(<UsersPage />)
    await screen.findByText('Ada Lovelace')
    getMock.mockClear()

    await userEvent.click(screen.getByRole('button', { name: /Sort by Name/ }))
    await waitFor(() => {
      const [, config] = getMock.mock.calls.find(([url]) => url === '/api/users')!
      expect(config.params.sort_by).toBe('full_name')
      expect(config.params.sort_direction).toBe('asc')
    })

    getMock.mockClear()
    await userEvent.click(screen.getByRole('button', { name: /Sort by Name/ }))
    await waitFor(() => {
      const [, config] = getMock.mock.calls.find(([url]) => url === '/api/users')!
      expect(config.params.sort_direction).toBe('desc')
    })
  })

  it('pagination Next requests the next page without resetting search', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/teams') return Promise.resolve({ data: TEAMS_RESPONSE })
      return Promise.resolve({ data: usersResponse([makeUser()], { total: 40, total_pages: 2 }) })
    })

    render(<UsersPage />)
    await screen.findByText('Ada Lovelace')
    getMock.mockClear()

    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => {
      const [, config] = getMock.mock.calls.find(([url]) => url === '/api/users')!
      expect(config.params.page).toBe(2)
    })
  })

  it('changing the page size requests it and resets to page 1', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/teams') return Promise.resolve({ data: TEAMS_RESPONSE })
      return Promise.resolve({ data: usersResponse([makeUser()], { total: 40, total_pages: 2 }) })
    })

    render(<UsersPage />)
    await screen.findByText('Ada Lovelace')
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(screen.getByText('Page 2 of 2')).toBeInTheDocument())
    getMock.mockClear()

    await userEvent.selectOptions(screen.getByRole('combobox'), '50')
    await waitFor(() => {
      const [, config] = getMock.mock.calls.find(([url]) => url === '/api/users')!
      expect(config.params.page_size).toBe(50)
      expect(config.params.page).toBe(1)
    })
  })

  it('creating a user refetches the current page', async () => {
    postMock.mockResolvedValue({ data: makeUser({ id: 2, username: 'new_hire' }) })
    render(<UsersPage />)
    await screen.findByText('Ada Lovelace')
    getMock.mockClear()

    await userEvent.click(screen.getByRole('button', { name: 'New User' }))
    await userEvent.type(screen.getByLabelText('Full name'), 'New Hire')
    await userEvent.type(screen.getByLabelText('Email'), 'new@example.com')
    await userEvent.type(screen.getByLabelText('Username'), 'new_hire')
    await userEvent.type(screen.getByLabelText('Password'), 'Str0ng!Pass1')
    await userEvent.click(screen.getByRole('button', { name: 'Create user' }))

    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/api/users', expect.objectContaining({ username: 'new_hire' })))
    await waitFor(() => {
      const calls = getMock.mock.calls.filter(([url]) => url === '/api/users')
      expect(calls.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('changing role shows an error message and does not crash on failure', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/teams') return Promise.resolve({ data: TEAMS_RESPONSE })
      // A different id than ADMIN's (1) -- otherwise the row's role
      // options are disabled as "can't change your own role."
      return Promise.resolve({ data: usersResponse([makeUser({ id: 5, role: 'team_member' })]) })
    })
    patchMock.mockRejectedValue(new Error('Failed to change role.'))

    render(<UsersPage />)
    await screen.findByText('Ada Lovelace')

    const row = screen.getByText('Ada Lovelace').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Set role: Admin'))

    expect(await screen.findByText('Failed to change role.')).toBeInTheDocument()
  })

  it("disables every role option and Deactivate on the current admin's own row", async () => {
    // Default makeUser() is id: 1 / role: 'admin', matching ADMIN above --
    // this row is the signed-in admin's own account. The backend rejects
    // both self-role-change and self-deactivation (app/api/users.py); this
    // pins down that the UI reflects the same rule, not just relies on it.
    render(<UsersPage />)
    await screen.findByText('Ada Lovelace')

    const row = screen.getByText('Ada Lovelace').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))

    const roleOptions = await screen.findAllByRole('menuitem', { name: /Set role:/ })
    expect(roleOptions.length).toBeGreaterThan(0)
    for (const option of roleOptions) {
      expect(option).toBeDisabled()
    }
    expect(screen.getByRole('menuitem', { name: 'Deactivate' })).toBeDisabled()
  })
})
