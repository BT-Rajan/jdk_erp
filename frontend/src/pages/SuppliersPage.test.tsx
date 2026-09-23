import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SuppliersPage } from './SuppliersPage'

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
const TEAM_MEMBER = { id: 2, full_name: 'Team Member', role: 'team_member' }

function makeSupplier(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    organisation_id: 1,
    code: 'SUP0001',
    name: 'Acme Traders',
    contact_person: 'Jane Doe',
    phone: '96512345678',
    email: 'jane@acme.example',
    address: 'Industrial Area, Plot 4',
    is_active: true,
    ...overrides,
  }
}

function suppliersResponse(
  data: ReturnType<typeof makeSupplier>[],
  overrides: Partial<{ page: number; page_size: number; total: number; total_pages: number }> = {},
) {
  return { data, pagination: { page: 1, page_size: 20, total: data.length, total_pages: 1, ...overrides } }
}

beforeEach(() => {
  useAuthMock.mockReset().mockReturnValue({ user: ADMIN })
  getMock.mockReset()
  postMock.mockReset()
  patchMock.mockReset()
  getMock.mockResolvedValue({ data: suppliersResponse([makeSupplier()]) })
})

describe('SuppliersPage', () => {
  it('loads and renders suppliers on mount, with exactly one initial request', async () => {
    render(<SuppliersPage />)

    expect(await screen.findByText('Acme Traders')).toBeInTheDocument()
    const calls = getMock.mock.calls.filter(([url]) => url === '/api/suppliers')
    expect(calls).toHaveLength(1)
  })

  it('shows the read-only view for a non-admin: list loads but no mutating controls appear', async () => {
    useAuthMock.mockReturnValue({ user: TEAM_MEMBER })
    render(<SuppliersPage />)

    expect(await screen.findByText('Acme Traders')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New Supplier' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Actions for/ })).not.toBeInTheDocument()
  })

  it('shows an error state when the request fails', async () => {
    getMock.mockRejectedValue(new Error('Network down'))
    render(<SuppliersPage />)
    expect(await screen.findByText('Network down')).toBeInTheDocument()
  })

  it('shows a distinct empty state for no suppliers at all vs. no search matches', async () => {
    getMock.mockResolvedValue({ data: suppliersResponse([]) })
    render(<SuppliersPage />)
    expect(await screen.findByText('No suppliers yet')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Search'), 'zzz')
    await waitFor(() => expect(screen.getByText('No matching suppliers')).toBeInTheDocument())
  })

  it('debounces search: types quickly but only fires one request with the final term, resetting to page 1', async () => {
    render(<SuppliersPage />)
    await screen.findByText('Acme Traders')
    getMock.mockClear()

    await userEvent.type(screen.getByLabelText('Search'), 'acme')

    await waitFor(() => {
      const calls = getMock.mock.calls.filter(([url]) => url === '/api/suppliers')
      expect(calls).toHaveLength(1)
    })
    const [, config] = getMock.mock.calls.find(([url]) => url === '/api/suppliers')!
    expect(config.params.q).toBe('acme')
    expect(config.params.page).toBe(1)
  })

  it('creating a supplier posts the payload and refetches the list', async () => {
    postMock.mockResolvedValue({ data: makeSupplier({ id: 2, name: 'Beta Chemicals', code: 'SUP0002' }) })
    render(<SuppliersPage />)
    await screen.findByText('Acme Traders')
    getMock.mockClear()

    await userEvent.click(screen.getByRole('button', { name: 'New Supplier' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Beta Chemicals')
    await userEvent.click(screen.getByRole('button', { name: 'Create supplier' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/suppliers', expect.objectContaining({ name: 'Beta Chemicals' })),
    )
    await waitFor(() => {
      const calls = getMock.mock.calls.filter(([url]) => url === '/api/suppliers')
      expect(calls.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('creating a supplier shows a server-side name conflict as a form error', async () => {
    const { ApiError } = await import('@/lib/apiClient')
    postMock.mockRejectedValue(new ApiError({ message: 'A supplier with this name already exists.', code: 'CONFLICT' }, 409))
    render(<SuppliersPage />)
    await screen.findByText('Acme Traders')

    await userEvent.click(screen.getByRole('button', { name: 'New Supplier' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Acme Traders')
    await userEvent.click(screen.getByRole('button', { name: 'Create supplier' }))

    expect(await screen.findByText('A supplier with this name already exists.')).toBeInTheDocument()
  })

  it('editing a supplier pre-fills the form and sends a PATCH', async () => {
    patchMock.mockResolvedValue({ data: makeSupplier({ name: 'Acme Trading Co' }) })
    render(<SuppliersPage />)
    await screen.findByText('Acme Traders')

    const row = screen.getByText('Acme Traders').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Edit'))

    expect(screen.getByLabelText('Name')).toHaveValue('Acme Traders')
    expect(screen.getByLabelText('Contact person')).toHaveValue('Jane Doe')
    await userEvent.clear(screen.getByLabelText('Name'))
    await userEvent.type(screen.getByLabelText('Name'), 'Acme Trading Co')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith(
        '/api/suppliers/1',
        expect.objectContaining({ name: 'Acme Trading Co' }),
      ),
    )
  })

  it('deactivating asks for confirmation, then calls the status endpoint and refetches', async () => {
    patchMock.mockResolvedValue({ data: makeSupplier({ is_active: false }) })
    render(<SuppliersPage />)
    await screen.findByText('Acme Traders')

    const row = screen.getByText('Acme Traders').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Deactivate'))
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledWith('/api/suppliers/1/status', { is_active: false }))
  })

  it('shows an error message when changing status fails', async () => {
    patchMock.mockRejectedValue(new Error('Failed to change status.'))
    render(<SuppliersPage />)
    await screen.findByText('Acme Traders')

    const row = screen.getByText('Acme Traders').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Deactivate'))
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    expect(await screen.findByText('Failed to change status.')).toBeInTheDocument()
  })
})
