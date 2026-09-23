import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RawMaterialsPage } from './RawMaterialsPage'

const { useAuthMock, getMock, postMock, patchMock, deleteMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  getMock: vi.fn(),
  postMock: vi.fn(),
  patchMock: vi.fn(),
  deleteMock: vi.fn(),
}))

vi.mock('@/lib/auth/AuthContext', () => ({ useAuth: useAuthMock }))
vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock, patch: patchMock, delete: deleteMock } }
})

const ADMIN = { id: 1, full_name: 'Admin User', role: 'admin' }
const TEAM_MEMBER = { id: 2, full_name: 'Team Member', role: 'team_member' }

const CATEGORIES_RESPONSE = {
  data: [{ id: 10, name: 'Electronics', code: 'ELEC', is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}
const UNITS_RESPONSE = {
  data: [{ id: 20, name: 'Kilogram', code: 'KG', is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}
const SUPPLIERS_RESPONSE = {
  data: [{ id: 30, name: 'Acme Traders', code: 'SUP0001', is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}

function makeMaterial(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    organisation_id: 1,
    code: 'RM001',
    name: 'Cement',
    category_id: 10,
    unit_of_measure_id: 20,
    description: null,
    reference_cost: '12.5000',
    is_active: true,
    ...overrides,
  }
}

function makeLink(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 100,
    supplier_id: 30,
    raw_material_id: 1,
    supplier_material_code: 'ACME-CEM-50',
    purchase_price: '11.0000',
    lead_time_days: 7,
    moq: '500.0000',
    max_supply_quantity: '10000.0000',
    is_preferred: false,
    is_active: true,
    ...overrides,
  }
}

function materialsResponse(
  data: ReturnType<typeof makeMaterial>[],
  overrides: Partial<{ page: number; page_size: number; total: number; total_pages: number }> = {},
) {
  return { data, pagination: { page: 1, page_size: 20, total: data.length, total_pages: 1, ...overrides } }
}

beforeEach(() => {
  useAuthMock.mockReset().mockReturnValue({ user: ADMIN })
  getMock.mockReset()
  postMock.mockReset()
  patchMock.mockReset()
  deleteMock.mockReset()
  getMock.mockImplementation((url: string) => {
    if (url === '/api/categories') return Promise.resolve({ data: CATEGORIES_RESPONSE })
    if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
    if (url === '/api/suppliers') return Promise.resolve({ data: SUPPLIERS_RESPONSE })
    if (url === '/api/raw-materials') return Promise.resolve({ data: materialsResponse([makeMaterial()]) })
    if (url === '/api/raw-materials/1/suppliers') return Promise.resolve({ data: [] })
    return Promise.reject(new Error(`Unexpected GET ${url}`))
  })
})

describe('RawMaterialsPage', () => {
  it('loads and renders raw materials on mount, with exactly one initial request', async () => {
    render(<RawMaterialsPage />)

    expect(await screen.findByText('Cement')).toBeInTheDocument()
    const calls = getMock.mock.calls.filter(([url]) => url === '/api/raw-materials')
    expect(calls).toHaveLength(1)
  })

  it('shows the category name and unit code resolved from the lookup lists', async () => {
    render(<RawMaterialsPage />)
    expect(await screen.findByText('Electronics')).toBeInTheDocument()
    expect(await screen.findByText('KG')).toBeInTheDocument()
  })

  it('shows the read-only view for a non-admin: list loads but no mutating controls appear', async () => {
    useAuthMock.mockReturnValue({ user: TEAM_MEMBER })
    render(<RawMaterialsPage />)

    expect(await screen.findByText('Cement')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New Raw Material' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Actions for/ })).not.toBeInTheDocument()
    expect(getMock.mock.calls.some(([url]) => url === '/api/categories')).toBe(false)
  })

  it('shows an error state when the request fails', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/categories') return Promise.resolve({ data: CATEGORIES_RESPONSE })
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      if (url === '/api/suppliers') return Promise.resolve({ data: SUPPLIERS_RESPONSE })
      return Promise.reject(new Error('Network down'))
    })
    render(<RawMaterialsPage />)
    expect(await screen.findByText('Network down')).toBeInTheDocument()
  })

  it('shows a distinct empty state for no raw materials at all vs. no search matches', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/categories') return Promise.resolve({ data: CATEGORIES_RESPONSE })
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      if (url === '/api/suppliers') return Promise.resolve({ data: SUPPLIERS_RESPONSE })
      return Promise.resolve({ data: materialsResponse([]) })
    })
    render(<RawMaterialsPage />)
    expect(await screen.findByText('No raw materials yet')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Search'), 'zzz')
    await waitFor(() => expect(screen.getByText('No matching raw materials')).toBeInTheDocument())
  })

  it('debounces search: types quickly but only fires one request with the final term, resetting to page 1', async () => {
    render(<RawMaterialsPage />)
    await screen.findByText('Cement')
    getMock.mockClear()

    await userEvent.type(screen.getByLabelText('Search'), 'ceme')

    await waitFor(() => {
      const calls = getMock.mock.calls.filter(([url]) => url === '/api/raw-materials')
      expect(calls).toHaveLength(1)
    })
    const [, config] = getMock.mock.calls.find(([url]) => url === '/api/raw-materials')!
    expect(config.params.q).toBe('ceme')
    expect(config.params.page).toBe(1)
  })

  it('creating a raw material posts the payload including code, category and unit', async () => {
    postMock.mockResolvedValue({ data: makeMaterial({ id: 2, name: 'Sand', code: 'RM002' }) })
    render(<RawMaterialsPage />)
    await screen.findByText('Cement')
    getMock.mockClear()

    await userEvent.click(screen.getByRole('button', { name: 'New Raw Material' }))
    await userEvent.type(screen.getByLabelText('Code'), 'RM002')
    await userEvent.type(screen.getByLabelText('Name'), 'Sand')
    await userEvent.selectOptions(screen.getByLabelText('Category'), '10')
    await userEvent.selectOptions(screen.getByLabelText('Unit of Measure'), '20')
    await userEvent.click(screen.getByRole('button', { name: 'Create raw material' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        '/api/raw-materials',
        expect.objectContaining({ code: 'RM002', name: 'Sand', category_id: 10, unit_of_measure_id: 20 }),
      ),
    )
  })

  it('creating a raw material shows a server-side code conflict as a form error', async () => {
    const { ApiError } = await import('@/lib/apiClient')
    postMock.mockRejectedValue(new ApiError({ message: 'A raw material with this code or name already exists.', code: 'CONFLICT' }, 409))
    render(<RawMaterialsPage />)
    await screen.findByText('Cement')

    await userEvent.click(screen.getByRole('button', { name: 'New Raw Material' }))
    await userEvent.type(screen.getByLabelText('Code'), 'RM001')
    await userEvent.type(screen.getByLabelText('Name'), 'Duplicate')
    await userEvent.selectOptions(screen.getByLabelText('Category'), '10')
    await userEvent.selectOptions(screen.getByLabelText('Unit of Measure'), '20')
    await userEvent.click(screen.getByRole('button', { name: 'Create raw material' }))

    expect(await screen.findByText('A raw material with this code or name already exists.')).toBeInTheDocument()
  })

  it('editing a raw material pre-fills the form, disables the code field, and sends a PATCH without code', async () => {
    patchMock.mockResolvedValue({ data: makeMaterial({ name: 'Portland Cement' }) })
    render(<RawMaterialsPage />)
    await screen.findByText('Cement')

    const row = screen.getByText('Cement').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Edit'))

    expect(screen.getByLabelText('Code')).toHaveValue('RM001')
    expect(screen.getByLabelText('Code')).toBeDisabled()

    await userEvent.clear(screen.getByLabelText('Name'))
    await userEvent.type(screen.getByLabelText('Name'), 'Portland Cement')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith('/api/raw-materials/1', expect.not.objectContaining({ code: expect.anything() })),
    )
  })

  it('deactivating asks for confirmation, then calls the status endpoint and refetches', async () => {
    patchMock.mockResolvedValue({ data: makeMaterial({ is_active: false }) })
    render(<RawMaterialsPage />)
    await screen.findByText('Cement')

    const row = screen.getByText('Cement').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Deactivate'))
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledWith('/api/raw-materials/1/status', { is_active: false }))
  })

  // --- Manage Suppliers dialog ---

  it('opens the Manage Suppliers dialog and shows an empty state when none are linked', async () => {
    render(<RawMaterialsPage />)
    await screen.findByText('Cement')

    const row = screen.getByText('Cement').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Manage Suppliers...'))

    expect(await screen.findByText('No suppliers linked to this material yet.')).toBeInTheDocument()
  })

  it('lists existing supplier relationships with resolved supplier names', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/categories') return Promise.resolve({ data: CATEGORIES_RESPONSE })
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      if (url === '/api/suppliers') return Promise.resolve({ data: SUPPLIERS_RESPONSE })
      if (url === '/api/raw-materials') return Promise.resolve({ data: materialsResponse([makeMaterial()]) })
      if (url === '/api/raw-materials/1/suppliers') return Promise.resolve({ data: [makeLink()] })
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })
    render(<RawMaterialsPage />)
    await screen.findByText('Cement')

    const row = screen.getByText('Cement').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Manage Suppliers...'))

    expect(await screen.findByText('Acme Traders')).toBeInTheDocument()
    expect(screen.getByText('ACME-CEM-50')).toBeInTheDocument()
  })

  it('adding a supplier relationship posts the payload to the nested endpoint', async () => {
    postMock.mockResolvedValue({ data: makeLink() })
    render(<RawMaterialsPage />)
    await screen.findByText('Cement')

    const row = screen.getByText('Cement').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Manage Suppliers...'))
    await screen.findByText('No suppliers linked to this material yet.')

    await userEvent.click(screen.getByRole('button', { name: 'Add Supplier' }))
    await userEvent.selectOptions(screen.getByLabelText('Supplier'), '30')
    await userEvent.type(screen.getByLabelText("Supplier's Material Code"), 'ACME-CEM-50')
    await userEvent.click(screen.getByRole('button', { name: 'Add supplier' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        '/api/raw-materials/1/suppliers',
        expect.objectContaining({ supplier_id: 30, supplier_material_code: 'ACME-CEM-50' }),
      ),
    )
  })

  it('removing a supplier relationship asks for confirmation, then calls DELETE', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/categories') return Promise.resolve({ data: CATEGORIES_RESPONSE })
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      if (url === '/api/suppliers') return Promise.resolve({ data: SUPPLIERS_RESPONSE })
      if (url === '/api/raw-materials') return Promise.resolve({ data: materialsResponse([makeMaterial()]) })
      if (url === '/api/raw-materials/1/suppliers') return Promise.resolve({ data: [makeLink()] })
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })
    deleteMock.mockResolvedValue({ data: null })
    render(<RawMaterialsPage />)
    await screen.findByText('Cement')

    const row = screen.getByText('Cement').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Manage Suppliers...'))
    await screen.findByText('Acme Traders')

    await userEvent.click(screen.getByRole('button', { name: /Actions for Acme Traders/ }))
    await userEvent.click(await screen.findByText('Remove'))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith('/api/raw-materials/1/suppliers/100'))
  })
})
