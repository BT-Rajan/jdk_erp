import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { CustomersPage } from './CustomersPage'

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
const MANAGER = { id: 2, full_name: 'Manager Person', role: 'manager' }
const TEAM_MEMBER = { id: 3, full_name: 'Team Member', role: 'team_member' }

const USERS_RESPONSE = {
  data: [
    { id: 1, full_name: 'Admin User', role: 'admin' },
    { id: 3, full_name: 'Salesman Sam', role: 'team_member' },
  ],
  pagination: { page: 1, page_size: 200, total: 2, total_pages: 1 },
}

function makeCustomer(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    organisation_id: 1,
    code: 'CUS00001',
    name: 'Acme Trading',
    contact_person: 'John Doe',
    phone: '96512345678',
    email: null,
    address: null,
    assigned_to_user_id: 3,
    is_active: true,
    ...overrides,
  }
}

function customersResponse(
  data: ReturnType<typeof makeCustomer>[],
  overrides: Partial<{ page: number; page_size: number; total: number; total_pages: number }> = {},
) {
  return { data, pagination: { page: 1, page_size: 20, total: data.length, total_pages: 1, ...overrides } }
}

beforeEach(() => {
  useAuthMock.mockReset().mockReturnValue({ user: ADMIN })
  getMock.mockReset()
  postMock.mockReset()
  patchMock.mockReset()
  getMock.mockImplementation((url: string) => {
    if (url === '/api/users') return Promise.resolve({ data: USERS_RESPONSE })
    if (url === '/api/customers') return Promise.resolve({ data: customersResponse([makeCustomer()]) })
    return Promise.reject(new Error(`Unexpected GET ${url}`))
  })
})

describe('CustomersPage', () => {
  it('loads and renders customers on mount, with exactly one initial request', async () => {
    render(<CustomersPage />, { wrapper: MemoryRouter })

    expect(await screen.findByText('Acme Trading')).toBeInTheDocument()
    const calls = getMock.mock.calls.filter(([url]) => url === '/api/customers')
    expect(calls).toHaveLength(1)
  })

  it('shows the assignee name resolved from the users list', async () => {
    render(<CustomersPage />, { wrapper: MemoryRouter })
    expect(await screen.findByText('Salesman Sam')).toBeInTheDocument()
  })

  it('shows Unassigned when a customer has no assignee', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/users') return Promise.resolve({ data: USERS_RESPONSE })
      return Promise.resolve({ data: customersResponse([makeCustomer({ assigned_to_user_id: null })]) })
    })
    render(<CustomersPage />, { wrapper: MemoryRouter })
    expect(await screen.findByText('Unassigned')).toBeInTheDocument()
  })

  it('a team_member sees the list and can create, but has no Edit/Assign/Deactivate actions', async () => {
    useAuthMock.mockReturnValue({ user: TEAM_MEMBER })
    render(<CustomersPage />, { wrapper: MemoryRouter })

    expect(await screen.findByText('Acme Trading')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New Customer' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Actions for/ })).not.toBeInTheDocument()
    // team_member never even fetches /api/users -- no assign capability.
    expect(getMock.mock.calls.some(([url]) => url === '/api/users')).toBe(false)
  })

  it('a manager sees Assign but not Edit/Deactivate', async () => {
    useAuthMock.mockReturnValue({ user: MANAGER })
    render(<CustomersPage />, { wrapper: MemoryRouter })
    await screen.findByText('Acme Trading')

    const row = screen.getByText('Acme Trading').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))

    expect(screen.getByText('Assign...')).toBeInTheDocument()
    expect(screen.queryByText('Edit')).not.toBeInTheDocument()
    expect(screen.queryByText('Deactivate')).not.toBeInTheDocument()
  })

  it('an admin sees Edit, Assign, and Deactivate', async () => {
    render(<CustomersPage />, { wrapper: MemoryRouter })
    await screen.findByText('Acme Trading')

    const row = screen.getByText('Acme Trading').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))

    expect(screen.getByText('Edit')).toBeInTheDocument()
    expect(screen.getByText('Assign...')).toBeInTheDocument()
    expect(screen.getByText('Deactivate')).toBeInTheDocument()
  })

  it('shows an error state when the request fails', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/users') return Promise.resolve({ data: USERS_RESPONSE })
      return Promise.reject(new Error('Network down'))
    })
    render(<CustomersPage />, { wrapper: MemoryRouter })
    expect(await screen.findByText('Network down')).toBeInTheDocument()
  })

  it('debounces search: types quickly but only fires one request with the final term, resetting to page 1', async () => {
    render(<CustomersPage />, { wrapper: MemoryRouter })
    await screen.findByText('Acme Trading')
    getMock.mockClear()

    await userEvent.type(screen.getByLabelText('Search'), 'acme')

    await waitFor(() => {
      const calls = getMock.mock.calls.filter(([url]) => url === '/api/customers')
      expect(calls).toHaveLength(1)
    })
    const [, config] = getMock.mock.calls.find(([url]) => url === '/api/customers')!
    expect(config.params.q).toBe('acme')
    expect(config.params.page).toBe(1)
  })

  it('creating a customer posts the payload and refetches the list', async () => {
    postMock.mockResolvedValue({ data: makeCustomer({ id: 2, name: 'New Co' }) })
    render(<CustomersPage />, { wrapper: MemoryRouter })
    await screen.findByText('Acme Trading')
    getMock.mockClear()

    await userEvent.click(screen.getByRole('button', { name: 'New Customer' }))
    await userEvent.type(screen.getByLabelText('Name'), 'New Co')
    await userEvent.click(screen.getByRole('button', { name: 'Create customer' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/customers', expect.objectContaining({ name: 'New Co' })),
    )
    await waitFor(() => {
      const calls = getMock.mock.calls.filter(([url]) => url === '/api/customers')
      expect(calls.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('editing a customer pre-fills the form and sends a PATCH', async () => {
    patchMock.mockResolvedValue({ data: makeCustomer({ name: 'Renamed Co' }) })
    render(<CustomersPage />, { wrapper: MemoryRouter })
    await screen.findByText('Acme Trading')

    const row = screen.getByText('Acme Trading').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Edit'))

    expect(screen.getByLabelText('Name')).toHaveValue('Acme Trading')
    await userEvent.clear(screen.getByLabelText('Name'))
    await userEvent.type(screen.getByLabelText('Name'), 'Renamed Co')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith('/api/customers/1', expect.objectContaining({ name: 'Renamed Co' })),
    )
  })

  it('deactivating asks for confirmation, then calls the status endpoint and refetches', async () => {
    patchMock.mockResolvedValue({ data: makeCustomer({ is_active: false }) })
    render(<CustomersPage />, { wrapper: MemoryRouter })
    await screen.findByText('Acme Trading')

    const row = screen.getByText('Acme Trading').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Deactivate'))
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledWith('/api/customers/1/status', { is_active: false }))
  })

  it('assigning a customer sends the selected user id to the assign endpoint', async () => {
    patchMock.mockResolvedValue({ data: makeCustomer({ assigned_to_user_id: 1 }) })
    render(<CustomersPage />, { wrapper: MemoryRouter })
    await screen.findByText('Acme Trading')
    await screen.findByText('Salesman Sam')

    const row = screen.getByText('Acme Trading').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Assign...'))

    await userEvent.selectOptions(screen.getByLabelText('Assigned to'), '1')
    await userEvent.click(screen.getByRole('button', { name: 'Save assignment' }))

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith('/api/customers/1/assign', { assigned_to_user_id: 1 }),
    )
  })

  it('assigning to Unassigned sends null', async () => {
    patchMock.mockResolvedValue({ data: makeCustomer({ assigned_to_user_id: null }) })
    render(<CustomersPage />, { wrapper: MemoryRouter })
    await screen.findByText('Acme Trading')
    await screen.findByText('Salesman Sam')

    const row = screen.getByText('Acme Trading').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Assign...'))

    await userEvent.selectOptions(screen.getByLabelText('Assigned to'), '')
    await userEvent.click(screen.getByRole('button', { name: 'Save assignment' }))

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith('/api/customers/1/assign', { assigned_to_user_id: null }),
    )
  })
})
