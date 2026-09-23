import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { WarehousesPage } from './WarehousesPage'

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

const UNITS_RESPONSE = {
  data: [{ id: 20, name: 'Square Metre', code: 'SQM', is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}

function makeWarehouse(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    organisation_id: 1,
    code: 'WH-001',
    name: 'Factory Warehouse',
    total_usable_storage_area: '5000.00',
    storage_area_unit_of_measure_id: 20,
    is_active: true,
    ...overrides,
  }
}

function warehousesResponse(
  data: ReturnType<typeof makeWarehouse>[],
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
    if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
    if (url === '/api/warehouses') return Promise.resolve({ data: warehousesResponse([makeWarehouse()]) })
    return Promise.reject(new Error(`Unexpected GET ${url}`))
  })
})

describe('WarehousesPage', () => {
  it('loads and renders warehouses on mount, with exactly one initial request', async () => {
    render(<WarehousesPage />)

    expect(await screen.findByText('Factory Warehouse')).toBeInTheDocument()
    const calls = getMock.mock.calls.filter(([url]) => url === '/api/warehouses')
    expect(calls).toHaveLength(1)
  })

  it('shows the formatted storage capacity resolved from the lookup list', async () => {
    render(<WarehousesPage />)
    expect(await screen.findByText('5000.00 SQM')).toBeInTheDocument()
  })

  it('shows the read-only view for a non-admin: list loads but no mutating controls appear', async () => {
    useAuthMock.mockReturnValue({ user: TEAM_MEMBER })
    render(<WarehousesPage />)

    expect(await screen.findByText('Factory Warehouse')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New Warehouse' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Actions for/ })).not.toBeInTheDocument()
    expect(getMock.mock.calls.some(([url]) => url === '/api/units-of-measure')).toBe(false)
  })

  it('shows an error state when the request fails', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      return Promise.reject(new Error('Network down'))
    })
    render(<WarehousesPage />)
    expect(await screen.findByText('Network down')).toBeInTheDocument()
  })

  it('shows a distinct empty state for no warehouses at all vs. no search matches', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      return Promise.resolve({ data: warehousesResponse([]) })
    })
    render(<WarehousesPage />)
    expect(await screen.findByText('No warehouses yet')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Search'), 'zzz')
    await waitFor(() => expect(screen.getByText('No matching warehouses')).toBeInTheDocument())
  })

  it('creating a warehouse posts the payload including structured capacity, with no code field', async () => {
    postMock.mockResolvedValue({ data: makeWarehouse({ id: 2, name: 'Second Warehouse', code: '000031' }) })
    render(<WarehousesPage />)
    await screen.findByText('Factory Warehouse')
    getMock.mockClear()

    await userEvent.click(screen.getByRole('button', { name: 'New Warehouse' }))
    expect(screen.queryByLabelText('Code')).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Name'), 'Second Warehouse')
    await userEvent.type(screen.getByLabelText('Total Usable Storage Area'), '3000')
    await userEvent.selectOptions(screen.getByLabelText('Storage Area Unit'), '20')
    await userEvent.click(screen.getByRole('button', { name: 'Create warehouse' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        '/api/warehouses',
        expect.objectContaining({
          name: 'Second Warehouse',
          total_usable_storage_area: '3000',
          storage_area_unit_of_measure_id: 20,
        }),
      ),
    )
  })

  it('rejects a non-positive storage area inline before submitting', async () => {
    render(<WarehousesPage />)
    await screen.findByText('Factory Warehouse')

    await userEvent.click(screen.getByRole('button', { name: 'New Warehouse' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Second Warehouse')
    await userEvent.type(screen.getByLabelText('Total Usable Storage Area'), '0')
    await userEvent.selectOptions(screen.getByLabelText('Storage Area Unit'), '20')
    await userEvent.click(screen.getByRole('button', { name: 'Create warehouse' }))

    expect(await screen.findByText('Enter a positive number')).toBeInTheDocument()
    expect(postMock).not.toHaveBeenCalled()
  })

  it('editing a warehouse pre-fills the form, disables the code field, and reconfigures capacity without a code change', async () => {
    patchMock.mockResolvedValue({ data: makeWarehouse({ total_usable_storage_area: '6000.00' }) })
    render(<WarehousesPage />)
    await screen.findByText('Factory Warehouse')

    const row = screen.getByText('Factory Warehouse').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Edit'))

    expect(screen.getByLabelText('Code')).toHaveValue('WH-001')
    expect(screen.getByLabelText('Code')).toBeDisabled()

    await userEvent.clear(screen.getByLabelText('Total Usable Storage Area'))
    await userEvent.type(screen.getByLabelText('Total Usable Storage Area'), '6000')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith(
        '/api/warehouses/1',
        expect.objectContaining({ total_usable_storage_area: '6000' }),
      ),
    )
    const [, payload] = patchMock.mock.calls[0]
    expect(payload.code).toBeUndefined()
  })

  it('deactivating asks for confirmation, then calls the status endpoint and refetches', async () => {
    patchMock.mockResolvedValue({ data: makeWarehouse({ is_active: false }) })
    render(<WarehousesPage />)
    await screen.findByText('Factory Warehouse')

    const row = screen.getByText('Factory Warehouse').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Deactivate'))
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledWith('/api/warehouses/1/status', { is_active: false }))
  })
})
